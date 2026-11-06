"""Rapports GHOST : ce qui est REEL (calcule localement) est etiquete [REAL], le reste [SIMULATED].

Regles : aucune recherche reseau ; aucune identite inventee (« UNVERIFIED ») ; les adresses IP fictives viennent des
plages reservees a la documentation (RFC 5737 : 192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) ; le niveau de menace est
une mise en scene deterministe (meme cible -> meme resultat), jamais une evaluation reelle.
"""
from __future__ import annotations

import hashlib
import re

PLAGES_DOC = ("192.0.2", "198.51.100", "203.0.113")
NIVEAUX = ("LOW", "MODERATE", "ELEVATED", "HIGH", "CRITICAL")
_RX_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_RX_EMAIL_STRICT = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$")
DOMAINES_JETABLES = {"mailinator.com", "yopmail.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
                     "trashmail.com", "sharklasers.com"}          # liste locale minimale, indicatif
CIBLE_DEMO = "cible@example.com"


def extraire_adresse(phrase: str) -> str:
    m = _RX_EMAIL.search(str(phrase or ""))
    return m.group(0) if m else ""


def _empreinte(texte: str) -> int:
    return int(hashlib.sha256(texte.lower().encode("utf-8")).hexdigest()[:8], 16)


def ip_fictive(cible: str) -> str:
    h = _empreinte(cible)
    return f"{PLAGES_DOC[h % 3]}.{(h >> 8) % 253 + 1}"


def niveau_menace(cible: str) -> str:
    return NIVEAUX[(_empreinte(cible + "#menace") % 3) + 2]            # ELEVATED / HIGH / CRITICAL (mise en scene)


def analyser_adresse(adresse: str) -> dict:
    """Analyse REELLE (locale, sans reseau) du format de l'adresse + champs simules."""
    a = str(adresse or "").strip()
    valide = bool(_RX_EMAIL_STRICT.match(a))
    local, _, domaine = a.partition("@")
    labels = domaine.lower().split(".") if domaine else []
    return {
        "adresse": a, "format_valide": valide, "partie_locale": local, "domaine": domaine.lower(),
        "tld": labels[-1] if labels else "", "nb_labels": len(labels),
        "domaine_jetable": domaine.lower() in DOMAINES_JETABLES,
        "longueur_locale": len(local), "contient_plus": "+" in local,
        "identite": "UNVERIFIED", "ip_fictive": ip_fictive(a or CIBLE_DEMO), "menace": niveau_menace(a or CIBLE_DEMO),
    }


def rapport_recon(adresse: str, demo: bool = False) -> str:
    d = analyser_adresse(adresse)
    cible = d["adresse"] or CIBLE_DEMO
    lignes = ["GHOST RECON", "-" * 32,
              f"TARGET       : {cible}" + ("  (DEMO TARGET)" if demo else ""),
              f"FORMAT       : {'VALID' if d['format_valide'] else 'INVALID'}   [REAL, local check]",
              f"DOMAIN       : {d['domaine'] or 'n/a'}   [REAL, from the address text]",
              f"DISPOSABLE   : {'YES' if d['domaine_jetable'] else 'NO'}   [REAL, small local list - not exhaustive]",
              f"IDENTITY     : {d['identite']}   [no lookup performed]",
              f"IP ADDRESS   : {d['ip_fictive']}   [SIMULATED - documentation range, not a real host]",
              f"THREAT LEVEL : {d['menace']}   [SIMULATED]",
              "MODE         : CINEMATIC SIMULATION", "-" * 32, "ANALYSIS COMPLETED"]
    return "\n".join(lignes)


def lignes_intelligence(graine: str = "ghost") -> list[str]:
    h = _empreinte(graine)
    return [f"synthetic records indexed : {1000 + h % 900}",
            f"simulated indicators      : {20 + h % 30}",
            f"anomalies (virtual)       : {1 + h % 5}",
            f"confidence                : {60 + h % 35} % (SIMULATED)"]


def rapport_intelligence(graine: str = "ghost") -> str:
    h = _empreinte(graine + "#i")
    menace = NIVEAUX[(h % 3) + 1]
    return "\n".join(["GHOST INTELLIGENCE", "-" * 32, *("  " + l for l in lignes_intelligence(graine)),
                      f"THREAT ASSESSMENT : {menace}   [SIMULATED]", "DATA SOURCES      : SYNTHETIC DATASET",
                      "MODE              : CINEMATIC SIMULATION", "-" * 32, "REPORT READY"])
