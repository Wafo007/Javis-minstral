"""Gestionnaire de fournisseurs LLM pour les missions autonomes (Mistral et Gemini gratuits uniquement).

Une mission longue consomme beaucoup d'appels : les quotas gratuits seront atteints. Ce module garantit
qu'un quota (HTTP 429) ou une panne n'est jamais une erreur fatale :

- detection du 429 (et des 5xx / delais depasses), lecture de ``Retry-After`` (secondes ou date HTTP) ;
- attente exponentielle avec gigue, jamais plus longue que ``attente_max`` entre deux essais ;
- bascule vers l'autre fournisseur s'il est configure ET pas lui-meme en quarantaine (on ne suppose pas
  qu'il est disponible) ;
- nombre d'essais borne ; quand tout est bloque trop longtemps : ``QuotaEnAttente(reprise_a)`` -- la mission
  sauvegarde son etat et reprend quand le quota le permet (elle n'echoue pas) ;
- budgets configurables (requetes, tokens) : ``BudgetEpuise`` quand ils sont atteints.

Aucun appel reseau n'est fait ici sans client : les « fournisseurs » sont des objets avec ``nom`` et
``completer(messages) -> (texte, tokens)``, ce qui permet de les remplacer dans les tests (doublures
explicitement etiquetees comme telles).
"""
from __future__ import annotations

import email.utils
import logging
import random
import time

LOG = logging.getLogger("jarvis.fournisseurs_mission")


class ErreurFournisseur(RuntimeError):
    """Aucun fournisseur n'a pu repondre (configuration absente, erreur d'authentification...)."""


class QuotaEnAttente(Exception):
    """Tous les fournisseurs sont limites : reprendre a ``reprise_a`` (horloge murale, secondes epoch)."""

    def __init__(self, reprise_a: float, detail: str = ""):
        super().__init__(detail or "quota atteint")
        self.reprise_a = float(reprise_a)
        self.detail = detail


class BudgetEpuise(Exception):
    """Budget de requetes ou de tokens atteint."""


def _statut(exc) -> int | None:
    for src in (exc, getattr(exc, "response", None)):
        for attr in ("status_code", "status", "code"):
            v = getattr(src, attr, None)
            if isinstance(v, int) and 100 <= v < 600:
                return v
    return None


def lire_retry_after(exc) -> float | None:
    """Valeur de l'en-tete Retry-After (secondes ou date HTTP) en secondes, sinon None."""
    rep = getattr(exc, "response", None)
    entetes = getattr(rep, "headers", None) or getattr(exc, "headers", None) or {}
    try:
        brut = entetes.get("retry-after") or entetes.get("Retry-After")
    except AttributeError:
        brut = None
    if brut in (None, ""):
        brut = getattr(exc, "retry_after", None)
    if brut in (None, ""):
        return None
    try:
        return max(0.0, float(brut))
    except (TypeError, ValueError):
        pass
    try:
        dt = email.utils.parsedate_to_datetime(str(brut))
        return max(0.0, dt.timestamp() - time.time())
    except (TypeError, ValueError):
        return None


def classer_erreur(exc) -> tuple[str, float | None]:
    """('quota' | 'transitoire' | 'auth' | 'fatale', retry_after)."""
    statut = _statut(exc)
    texte = str(exc).lower()
    if statut == 429 or "rate limit" in texte or "quota" in texte or "resource_exhausted" in texte \
            or "too many requests" in texte:
        return "quota", lire_retry_after(exc)
    if statut in (401, 403):
        return "auth", None
    if statut is not None and statut >= 500 or statut in (408, 409) or any(
            m in texte for m in ("timeout", "timed out", "connection", "overloaded", "high demand", "unavailable")):
        return "transitoire", lire_retry_after(exc)
    return "fatale", None


class GestionnaireFournisseurs:
    """Appelle les fournisseurs dans l'ordre de preference, avec quotas, attentes et budgets."""

    def __init__(self, fournisseurs, *, max_essais=6, attente_base=2.0, attente_max=60.0,
                 attente_inline_max=120.0, budget_requetes=0, budget_tokens=0,
                 dormir=time.sleep, horloge=time.time, hasard=random.random, rappel_attente=None):
        self.fournisseurs = list(fournisseurs)
        self.max_essais = max(1, int(max_essais))
        self.attente_base = float(attente_base)
        self.attente_max = float(attente_max)
        self.attente_inline_max = float(attente_inline_max)
        self.budget_requetes = int(budget_requetes or 0)       # 0 = illimite
        self.budget_tokens = int(budget_tokens or 0)
        self.requetes = 0
        self.tokens = 0
        self.quarantaine: dict[str, float] = {}               # nom -> horloge murale de fin de quarantaine
        self.evenements: list[dict] = []                       # trace pour le journal de mission
        self._dormir, self._horloge, self._hasard = dormir, horloge, hasard
        self._rappel_attente = rappel_attente                  # appele pendant les attentes (pause/annulation)

    # -- etat sauvegardable par la mission ------------------------------------------------------
    def etat(self) -> dict:
        return {"requetes": self.requetes, "tokens": self.tokens, "quarantaine": dict(self.quarantaine)}

    def restaurer(self, etat: dict | None):
        etat = etat or {}
        self.requetes = int(etat.get("requetes", 0))
        self.tokens = int(etat.get("tokens", 0))
        self.quarantaine = {k: float(v) for k, v in (etat.get("quarantaine") or {}).items()}

    def _noter(self, type_, **kw):
        ev = {"ts": self._horloge(), "type": type_, **kw}
        self.evenements.append(ev)
        del self.evenements[:-200]
        LOG.info("fournisseur %s %s", type_, kw)

    def _delai(self, essai: int, retry_after: float | None) -> float:
        exponentiel = min(self.attente_max, self.attente_base * (2 ** essai))
        gigue = exponentiel * 0.25 * self._hasard()
        delai = exponentiel + gigue
        if retry_after is not None:
            delai = max(delai, retry_after)                    # on ne rappelle jamais avant Retry-After
        return delai

    def _verifier_budgets(self):
        if self.budget_requetes and self.requetes >= self.budget_requetes:
            raise BudgetEpuise(f"budget de requetes atteint ({self.requetes}/{self.budget_requetes})")
        if self.budget_tokens and self.tokens >= self.budget_tokens:
            raise BudgetEpuise(f"budget de tokens atteint ({self.tokens}/{self.budget_tokens})")

    def _attendre(self, secondes: float):
        """Attente fractionnee : le rappel (pause/annulation) peut lever une exception pour l'interrompre."""
        fin = self._horloge() + secondes
        while True:
            reste = fin - self._horloge()
            if reste <= 0:
                return
            if self._rappel_attente:
                self._rappel_attente()
            self._dormir(min(1.0, reste))

    def appeler(self, messages) -> tuple[str, str]:
        """Renvoie (texte, nom_fournisseur). Voir la docstring du module pour les exceptions."""
        if not self.fournisseurs:
            raise ErreurFournisseur("aucun fournisseur LLM configure (cle Mistral ou Gemini manquante)")
        derniere = None
        essai = -1
        while essai + 1 < self.max_essais:
            self._verifier_budgets()
            maintenant = self._horloge()
            disponibles = [f for f in self.fournisseurs if self.quarantaine.get(f.nom, 0) <= maintenant]
            if not disponibles:
                reprise = min(self.quarantaine[f.nom] for f in self.fournisseurs)
                attente = reprise - maintenant
                if attente > self.attente_inline_max:
                    self._noter("quota_en_attente", reprise_a=reprise)
                    raise QuotaEnAttente(reprise, "tous les fournisseurs sont limites")
                self._noter("attente_quota", secondes=round(attente, 1))
                self._attendre(attente)                      # une attente n'est pas un essai
                continue
            essai += 1
            f = disponibles[0]
            try:
                self.requetes += 1
                texte, tokens = f.completer(messages)
                self.tokens += int(tokens or 0)
                if not isinstance(texte, str) or not texte.strip():
                    raise ValueError("reponse vide du fournisseur")
                return texte, f.nom
            except (BudgetEpuise, QuotaEnAttente):
                raise
            except Exception as exc:                            # noqa: BLE001 -- classee ci-dessous
                derniere = exc
                genre, retry_after = classer_erreur(exc)
                if isinstance(exc, ValueError):
                    genre = "transitoire"
                self._noter("erreur", fournisseur=f.nom, genre=genre, statut=_statut(exc), retry_after=retry_after)
                if genre == "auth":
                    self.quarantaine[f.nom] = self._horloge() + 3600     # cle invalide : inutile de reessayer
                    continue
                if genre == "fatale":
                    raise ErreurFournisseur(f"{f.nom} : {exc}") from exc
                delai = self._delai(essai, retry_after)
                self.quarantaine[f.nom] = self._horloge() + delai
                if len(self.fournisseurs) > 1 and any(
                        g.nom != f.nom and self.quarantaine.get(g.nom, 0) <= self._horloge()
                        for g in self.fournisseurs):
                    self._noter("bascule", de=f.nom)
        raise ErreurFournisseur(f"echec apres {self.max_essais} essais : {derniere}")


# ----------------------------------------------------------------------------------------------
# Fournisseurs reels (Mistral / Gemini via les clients OpenAI-compatibles de core.cloud)
# ----------------------------------------------------------------------------------------------
class FournisseurOpenAICompatible:
    def __init__(self, nom, client, modele, temperature=0.2, max_tokens=4096):
        self.nom, self.client, self.modele = nom, client, modele
        self.temperature, self.max_tokens = temperature, max_tokens

    def completer(self, messages):
        rep = self.client.chat.completions.create(
            model=self.modele, messages=messages, temperature=self.temperature, max_tokens=self.max_tokens)
        texte = (rep.choices[0].message.content or "") if rep.choices else ""
        usage = getattr(rep, "usage", None)
        tokens = getattr(usage, "total_tokens", 0) if usage else 0
        try:
            from core import cloud
            cloud.enregistrer_usage(rep, self.nom, self.modele)
        except Exception:                                       # le suivi des couts ne doit jamais casser la mission
            LOG.debug("enregistrer_usage indisponible", exc_info=True)
        return texte, tokens


def fournisseurs_configures():
    """[Mistral, Gemini] selon les cles presentes (gratuits uniquement ; ordre configurable)."""
    from core import cloud
    from core.config import reglage
    ordre = reglage("missions.fournisseurs", ["mistral", "gemini"]) or ["mistral", "gemini"]
    res = []
    for nom in ordre:
        try:
            if nom == "mistral":
                client = cloud.client_mistral()
                modele = str(reglage("missions.modele_mistral", "") or reglage("mistral.modele", "mistral-small-latest"))
            elif nom == "gemini":
                client = cloud.client_gemini()
                modele = str(reglage("missions.modele_gemini", "") or reglage("gemini.modele", "gemini-2.0-flash"))
            else:
                continue
        except Exception:
            LOG.warning("fournisseur %s indisponible", nom, exc_info=True)
            continue
        if client is not None:
            res.append(FournisseurOpenAICompatible(nom, client, modele))
    return res
