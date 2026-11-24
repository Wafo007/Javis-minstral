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
_RX_SITUATION = re.compile(r"\b(?:rapport de situation|statut (?:du )?systeme|etat (?:du|de la) (?:systeme|machine)|diagnostic|"
                           r"comment va (?:la machine|le systeme)|scan (?:interne|systeme))\b")
_RX_IDENTITE = re.compile(r"\b(?:qui es tu|qui est tu|tu es qui|presente toi|c est quoi ghost)\b")
_RX_VOIX_ETAT = re.compile(r"\b(?:etat|statut)\b.*\bvoix ghost\b|\bvoix ghost\b.*\b(?:etat|statut)\b")


def normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKD", str(texte or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9@ ]+", " ", t.replace("-", " ").replace("'", " "))
    return re.sub(r"\s+", " ", t).strip()


# --- detection floue du nom du mode (le STT Vosk francais ecorche « ghost protocol » : « gost protocole », « mode haker »...)
_REMPLACEMENTS_PHON = (("gh", "g"), ("ck", "k"), ("ph", "f"), ("qu", "k"), ("ch", "c"), ("c", "k"), ("w", "u"), ("y", "i"),
                       ("x", "ks"), ("h", ""), ("eur", "er"), ("oo", "u"), ("ou", "u"))
_CLES_NOM = ("gostprotokol", "protokolgost", "modegost", "gostmode", "modeaker", "akermode", "protokolaker")


def _phon(texte: str) -> str:
    """Forme phonetique grossiere sans espaces."""
    t = re.sub(r"[^a-z]", "", normaliser(texte))
    for a, b in _REMPLACEMENTS_PHON:
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)
    return re.sub(r"e$", "", t)


def _flou(segment: str, cle: str, seuil: float = 0.86) -> bool:
    from difflib import SequenceMatcher
    return abs(len(segment) - len(cle)) <= 3 and SequenceMatcher(None, segment, cle).ratio() >= seuil


def nomme_le_mode(phrase: str) -> bool:
    """Vrai si la phrase nomme le mode Ghost, meme mal transcrite. Le nom doit tenir dans 1 a 3 mots CONSECUTIFS
    (« ghost protocol », « go ste protocole ») : « le protocole de securite du poste » ne declenche rien."""
    mots = [_phon(m) for m in normaliser(phrase).split()]
    mots = [m for m in mots if m]
    for i in range(len(mots)):
        for k in (1, 2, 3):
            seg = "".join(mots[i:i + k])
            if seg and any(_flou(seg, c) for c in _CLES_NOM):
                return True
    return False


_RX_VERBE_ON = re.compile(r"\b(?:activ\w*|enclench\w*|lance\w*|demarr\w*|passe\w*|mets?|mettre|entre\w*|ouvre|ouvrir|initialis\w*|"
                          r"charge\w*|bascul\w*|va en|allons en|engage\w*)\b")
_RX_VERBE_OFF = re.compile(r"\b(?:desactiv\w*|quitt\w*|sors?|sortir|sortons|ferme\w*|arret\w*|stopp?\w*|coupe\w*|termin\w*|"
                           r"eteins?|eteindre|annul\w*|abandonn\w*)\b")
_RX_FIN_TACTIQUE = re.compile(r"\b(?:fin du mode (?:tactique|ghost|hacker)|retour a la normale|reviens a la normale|"
                              r"quitte le mode tactique|sors du mode tactique)\b")
_RX_QUESTION = re.compile(r"\b(?:c est quoi|qu est ce|explique\w*|comment|pourquoi|parle moi|dis moi ce|qui est|a quoi sert|"
                          r"documentation|tutoriel)\b")


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
    actif = ETAT.actif and not ETAT.sortie_en_attente
    explicite_scenario = (_RX_RECON_NOM.search(t) or _RX_INTEL_NOM.search(t) or _RX_ATTACK_NOM.search(t))
    nomme = nomme_le_mode(t) and not explicite_scenario
    # 1. desactivation d'abord (« quitte ghost protocol » contient aussi « ghost protocol »)
    if (nomme and _RX_VERBE_OFF.search(t)) or (ETAT.actif and _RX_FIN_TACTIQUE.search(t)):
        return ctrl.desactiver()
    if nomme:
        if _RX_VERBE_ON.search(t):
            return ctrl.activer()
        if not _RX_QUESTION.search(t) and len(t.split()) <= 6:      # le nom seul : « Ghost Protocol »
            return ctrl.activer()
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
    if actif:
        from modes.ghost_protocol import commandes_securite
        r = commandes_securite.essayer(phrase)
        if r:
            return r
    if not actif:
        return None                                  # toute autre phrase : comportement normal de Jarvis
    if _RX_SITUATION.search(t):
        return ctrl.rapport_situation()
    if _RX_IDENTITE.search(t):
        return ctrl.rep.choisir("identite", responses.IDENTITE)
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
