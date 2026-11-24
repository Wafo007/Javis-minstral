"""Contexte partage par les agents : cible, garde, client HTTP, journal, faits connus et resultats (dedoublonnes)."""
from __future__ import annotations

import threading

from modes.ghost_protocol.security.http_cadre import ClientCadre
from modes.ghost_protocol.security.modele import ORDRE_GRAVITE, Resultat


class AuditInterrompu(Exception):
    """Arret d'urgence ou arret demande : l'etape en cours s'arrete proprement."""


class Contexte:
    def __init__(self, cible, garde, journal, arret, client: ClientCadre | None = None, emettre=None):
        self.cible, self.garde, self.journal, self.arret = cible, garde, journal, arret
        self.client = client or ClientCadre(garde)
        self.emettre = emettre or (lambda *a, **k: None)
        self.faits: dict = {}
        self.carto = None
        self.resultats: dict[str, Resultat] = {}
        self.observations: list = []         # constats d'environnement (non vulnerabilites)
        self.limites: list = []              # ce qui n'a pas pu etre fait / verifie (honnetete du rapport)
        self._verrou = threading.Lock()

    def verifier_arret(self):
        if self.arret.actif():
            raise AuditInterrompu("arret demande")

    def ajouter(self, r: Resultat) -> Resultat:
        with self._verrou:
            ancien = self.resultats.get(r.id)
            if ancien is None:
                self.resultats[r.id] = r
                self.journal.ecrire("RESULTAT", id=r.id, categorie=r.categorie, gravite=r.gravite.value, ressource=r.ressource,
                                    statut=r.statut.value, agent=r.agent)
                self.emettre("resultat", r)
                return r
            if ORDRE_GRAVITE[r.gravite] > ORDRE_GRAVITE[ancien.gravite]:
                ancien.gravite = r.gravite
            ancien.confiance = max(ancien.confiance, r.confiance)
            return ancien

    def observer(self, texte: str):
        if texte not in self.observations:
            self.observations.append(texte)

    def limiter(self, texte: str):
        if texte not in self.limites:
            self.limites.append(texte)
            self.journal.ecrire("LIMITE", texte=texte)
