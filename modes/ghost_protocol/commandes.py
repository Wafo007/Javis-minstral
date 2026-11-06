"""Commandes vocales GHOST PROTOCOL : analyse locale (regex, accents ignores) -- aucun LLM, aucun reseau.

Utilisee en tete du routage (core/commandes_locales) : activation/desactivation fonctionnent meme si le LLM est HS.
Les formulations generiques (« analyse cette cible »...) ne sont captees que Ghost actif ; les noms explicites
(« lance Ghost Recon ») repondent toujours, par un rappel d'activation si le mode est inactif.
"""
from __future__ import annotations

import re
import unicodedata

from modes.ghost_protocol import fake_intelligence, responses
from modes.ghost_protocol.state_manager import ETAT

_MODE = r"(?:le )?(?:mode|protocole) (?:hacker|ghost)(?: protocol)?|ghost protocol|protocole ghost"
_RX_ACTIVER = re.compile(rf"\b(?:active|activer|enclenche|lance|demarre|passe en|mets? en|entre en)\b.*?(?:{_MODE})")
_RX_DESACTIVER = re.compile(rf"\b(?:desactive|desactiver|quitte|quitter|sors? (?:du|de)|sortir (?:du|de)|ferme|fermer|arrete|"
                            rf"stoppe|coupe|termine|eteins?)\b.*?(?:{_MODE})")
_RX_RECON_NOM = re.compile(r"\bghost recon\b")
_RX_INTEL_NOM = re.compile(r"\bghost intelligence\b")
_RX_ATTACK_NOM = re.compile(r"\bghost attack\b")
_RX_RECON_GEN = re.compile(r"\banalyse (?:cette|cet|l) ?(?:cible|adresse|e ?mail|mail)\b|\banalyse cette adresse\b")
_RX_INTEL_GEN = re.compile(r"\b(?:lance|demarre|fais)\b.*\banalyse complete\b")
_RX_ATTACK_GEN = re.compile(r"\bprepare\b.*\bsimulation d ?intrusion\b|\bsimulation d ?intrusion\b")
_RX_STOP_SIM = re.compile(r"\b(?:arrete|stoppe|annule|interromps|coupe)\b.*\bsimulation\b")
_RX_RUN = re.compile(r"\b(?:lance|execute|demarre)\b.*\b(?:la simulation|le script)\b")
_RX_VOIX_OFF = re.compile(r"\b(?:coupe|desactive|arrete)\b.*\bvoix ghost\b|\bvoix ghost\b.*\b(?:off|coupee|desactivee)\b")
_RX_VOIX_ON = re.compile(r"\b(?:retablis|reactive|remets?|active)\b.*\bvoix ghost\b")
_RX_VOIX_ETAT = re.compile(r"\b(?:etat|statut)\b.*\bvoix ghost\b|\bvoix ghost\b.*\b(?:etat|statut)\b")


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", str(texte or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9@ ]+", " ", t.replace("-", " ").replace("'", " "))
    return re.sub(r"\s+", " ", t).strip()


def adresse_dictee(texte: str) -> str:
    """Adresse ecrite, ou dictee (« jean arobase gmail point com »)."""
    a = fake_intelligence.extraire_adresse(texte)
    if a:
        return a
    t = normaliser(texte)
    m = re.search(r"([a-z0-9 ._+]+?) (?:arobase|at) ([a-z0-9 ]+?(?: point [a-z0-9]+)+)", t)
    if not m:
        return ""
    local = m.group(1).split()[-1] if " " in m.group(1).strip() else m.group(1).strip()
    dom = m.group(2).replace(" point ", ".").replace(" ", "")
    return f"{local}@{dom}"


def essayer(phrase: str, ctrl=None):
    """Renvoie la reponse a dire, ou None si la phrase n'est pas une commande Ghost."""
    t = normaliser(phrase)
    if not t:
        return None
    if ctrl is None:
        from modes.ghost_protocol import controleur
        ctrl = controleur()
    # 1. desactivation d'abord (« quitte ghost protocol » contient aussi « ghost protocol »)
    if _RX_DESACTIVER.search(t):
        return ctrl.desactiver()
    if _RX_ACTIVER.search(t) and not _RX_RECON_NOM.search(t) and not _RX_INTEL_NOM.search(t) and not _RX_ATTACK_NOM.search(t):
        return ctrl.activer()
    actif = ETAT.actif and not ETAT.sortie_en_attente
    nom = _RX_RECON_NOM.search(t) or _RX_INTEL_NOM.search(t) or _RX_ATTACK_NOM.search(t)
    if nom and not actif:
        return ctrl.rep.choisir("inactif", responses.INACTIF)
    if _RX_VOIX_ON.search(t) and (actif or nom):
        from modes.ghost_protocol import voice_manager
        voice_manager.couper_voix_ghost(False)
        return ctrl.rep.choisir("voix_on", responses.VOIX_RETABLIE)
    if _RX_VOIX_OFF.search(t) and actif:
        from modes.ghost_protocol import voice_manager
        voice_manager.couper_voix_ghost(True)
        return ctrl.rep.choisir("voix_off", responses.VOIX_COUPEE)
    if _RX_VOIX_ETAT.search(t):
        from modes.ghost_protocol import voice_manager
        return voice_manager.statut_texte()
    if not actif:
        return None                                  # toute autre phrase : comportement normal de Jarvis
    if _RX_STOP_SIM.search(t):
        return ctrl.arreter_simulation()
    if _RX_RUN.search(t) and ctrl.dernier_script:
        ctrl.run_script()
        return "Exécution de la simulation locale, isolée du réseau."
    if _RX_ATTACK_NOM.search(t) or _RX_ATTACK_GEN.search(t):
        return ctrl.lancer_attack()
    if _RX_INTEL_NOM.search(t) or _RX_INTEL_GEN.search(t):
        return ctrl.lancer_intelligence()
    if _RX_RECON_NOM.search(t) or _RX_RECON_GEN.search(t):
        return ctrl.lancer_recon(adresse_dictee(phrase))
    return None
