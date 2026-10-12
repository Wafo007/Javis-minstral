"""Modes d'usage : normal, travail, gaming, nuit, ne pas deranger.

Distincts des « modes » lumieres (tools/modes.py) et du « mode » local/hybride/cloud.
Un mode regle uniquement : volume, vitesse de voix, longueur des reponses, niveau de
proactivite, discretion du HUD, voix (profil) et ambiance lumineuse optionnelle.
Etat memorise dans notes/.mode_usage.json tant qu'on ne le change pas. Le mode nuit peut
aussi s'activer seul sur une plage horaire (mode_nuit.auto).

Config (config.yaml) : voir config.example.yaml, sections `modes_usage` et `mode_nuit`.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata
from pathlib import Path

try:
    from core.config import reglage as _reglage
except Exception:                                     # tests hors projet
    def _reglage(chemin, defaut=None):
        return defaut

FICHIER = Path(__file__).resolve().parent.parent / "notes" / ".mode_usage.json"
MODES = ("normal", "travail", "gaming", "nuit", "ne_pas_deranger")
LIBELLES = {"normal": "normal", "travail": "travail", "gaming": "gaming", "nuit": "nuit",
            "ne_pas_deranger": "ne pas déranger"}

DEFAUTS = {
    "normal": {"volume": 1.0, "vitesse": 1.0, "longueur": "normale", "proactif": "tout",
               "hud": "normal", "voix": None, "lumieres": None},
    "travail": {"volume": 1.0, "vitesse": 1.0, "longueur": "courte", "proactif": "important",
                "hud": "normal", "voix": None, "lumieres": None},
    "gaming": {"volume": 1.0, "vitesse": 1.05, "longueur": "tres_courte", "proactif": "important",
               "hud": "discret", "voix": None, "lumieres": None},
    "nuit": {"volume": 0.5, "vitesse": 0.92, "longueur": "tres_courte", "proactif": "important",
             "hud": "discret", "voix": "nuit", "lumieres": None},
    "ne_pas_deranger": {"volume": 1.0, "vitesse": 1.0, "longueur": "courte", "proactif": "rien",
                        "hud": "discret", "voix": None, "lumieres": None},
}
# importance d'un message parle sans que l'utilisateur l'ait demande
IMPORTANCE = {"info": 0, "normal": 1, "important": 2, "critique": 3}
_SEUIL = {"tout": 0, "important": 2, "rien": 3}
_RAPPEL = [None]


def _sans_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


def normaliser_mode(texte):
    """'ne pas deranger', 'dnd', 'jeu', 'bureau'... -> nom canonique ou None."""
    t = re.sub(r"[^a-z ]", " ", _sans_accents(texte or ""))
    t = " ".join(t.split())
    if re.search(r"\bne pas deranger\b|\bdnd\b|\bpas de notification", t):
        return "ne_pas_deranger"
    for mode, motifs in (("nuit", r"\bnuit\b|\bnocturne\b"), ("gaming", r"\bgaming\b|\bjeu\b|\bjeux\b|\bgame\b"),
                         ("travail", r"\btravail\b|\bboulot\b|\bwork\b|\bbureau\b"),
                         ("normal", r"\bnormal\b|\bstandard\b|\bclassique\b")):
        if re.search(motifs, t):
            return mode
    return None


# ------------------------------------------------------------------ etat
def _lire():
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _ecrire(etat):
    try:
        FICHIER.parent.mkdir(parents=True, exist_ok=True)
        FICHIER.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _hhmm(valeur, defaut):
    try:
        h, m = str(valeur or defaut).split(":")
        return dt.time(int(h), int(m))
    except Exception:
        h, m = defaut.split(":")
        return dt.time(int(h), int(m))


def _dans_plage(now):
    debut = _hhmm(_reglage("mode_nuit.heure_debut", "23:00"), "23:00")
    fin = _hhmm(_reglage("mode_nuit.heure_fin", "07:00"), "07:00")
    t = now.time()
    return (debut <= t < fin) if debut < fin else (t >= debut or t < fin)


def _fin_plage(now):
    fin = _hhmm(_reglage("mode_nuit.heure_fin", "07:00"), "07:00")
    cible = dt.datetime.combine(now.date(), fin)
    return cible if cible > now else cible + dt.timedelta(days=1)


def nuit_auto_actif(now=None):
    now = now or dt.datetime.now()
    if not bool(_reglage("mode_nuit.auto", False)) or not _dans_plage(now):
        return False
    jusqu = _lire().get("nuit_desactivee_jusqu")
    try:
        if jusqu and dt.datetime.fromisoformat(jusqu) > now:
            return False
    except ValueError:
        pass
    return True


def mode_effectif(now=None):
    manuel = _lire().get("mode", "normal")
    if manuel in MODES and manuel != "normal":
        return manuel
    return "nuit" if nuit_auto_actif(now) else "normal"


def parametres(mode=None, now=None):
    mode = mode or mode_effectif(now)
    p = dict(DEFAUTS.get(mode, DEFAUTS["normal"]))
    surcharge = _reglage(f"modes_usage.{mode}", None)
    if isinstance(surcharge, dict):
        p.update({k: v for k, v in surcharge.items() if k in p})
    if mode == "nuit":                                  # raccourcis mode_nuit.volume / vitesse
        for cle in ("volume", "vitesse"):
            v = _reglage(f"mode_nuit.{cle}", None)
            if isinstance(v, (int, float)):
                p[cle] = float(v)
    manuel = _lire().get("proactif")
    if manuel in _SEUIL:
        p["proactif"] = manuel
    p["mode"] = mode
    return p


def definir_rappel(fonction):
    """jarvis14 enregistre ici ce qui doit suivre un changement de mode (voix, HUD...)."""
    _RAPPEL[0] = fonction


def _notifier(mode):
    if _RAPPEL[0]:
        try:
            _RAPPEL[0](mode, parametres(mode))
        except Exception:
            pass


def definir_mode(nom, now=None):
    mode = nom if nom in MODES else normaliser_mode(nom)
    if mode is None:
        return "Je ne connais pas ce mode. Les modes sont : normal, travail, gaming, nuit et ne pas déranger."
    now = now or dt.datetime.now()
    etat = _lire()
    etat["mode"] = mode
    etat.pop("proactif", None)
    if mode == "nuit":
        etat.pop("nuit_desactivee_jusqu", None)
    elif mode == "normal" and nuit_auto_actif(now):     # « reviens au normal » pendant la plage auto
        etat["nuit_desactivee_jusqu"] = _fin_plage(now).isoformat()
    _ecrire(etat)
    _notifier(mode_effectif(now))
    return f"Mode {LIBELLES[mode]} activé."


def desactiver_mode(nom, now=None):
    mode = nom if nom in MODES else normaliser_mode(nom)
    if mode is None or mode == "normal":
        return definir_mode("normal", now)
    if mode_effectif(now) != mode:
        return f"Le mode {LIBELLES[mode]} n'était pas actif."
    definir_mode("normal", now)
    return f"Mode {LIBELLES[mode]} désactivé."


def definir_proactif(actif, now=None):
    etat = _lire()
    etat["proactif"] = "tout" if actif else "rien"
    _ecrire(etat)
    return "Les suggestions et annonces spontanées sont activées." if actif else \
        "Je ne parlerai plus sans qu'on me le demande, sauf alarmes et minuteurs."


def proactif_autorise(importance="normal", now=None):
    niveau = IMPORTANCE.get(importance, 1)
    return niveau >= _SEUIL.get(parametres(now=now)["proactif"], 0)


def description(now=None):
    p = parametres(now=now)
    auto = " (automatique)" if p["mode"] == "nuit" and _lire().get("mode", "normal") == "normal" else ""
    return f"Mode {LIBELLES[p['mode']]}{auto}."


def consigne_systeme(now=None):
    """Complement de consigne pour le LLM selon le mode (longueur des reponses)."""
    p = parametres(now=now)
    texte = ""
    if p["longueur"] == "tres_courte":
        texte = (f"Mode {LIBELLES[p['mode']]} : reponds en quelques mots, une phrase tres courte, "
                 "sans details sauf si on te les demande.")
    elif p["longueur"] == "courte":
        texte = f"Mode {LIBELLES[p['mode']]} : reponses breves, une phrase, ton sobre."
    if p["mode"] == "travail":
        texte += " Ton professionnel ; privilegie les outils de productivite."
    return texte
