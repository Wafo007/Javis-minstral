"""Outils pour controler le telephone Android (par ADB, voir core/mobile_adb.py et docs/mobile_android.md).

Niveaux de permission :
- N1 (sans confirmation) : etat du telephone, lancer une app, ouvrir un lien, touches de navigation, media, defilement,
  envoyer une notification AU telephone ;
- N2 (confirmation vocale, memorisable puis revocable) : tout ce qui LIT des donnees privees ou AGIT dans une app --
  toucher/taper, lire l'ecran, capturer l'ecran, lire les notifications, position, PHOTO (camera).
Aucun de ces outils n'est expose au MCP / pont iPhone / Hermes : seul le PC de l'utilisatrice pilote le telephone.
Le routage « sur mon telephone » passe avant l'ouverture d'application du PC (sinon « lance WhatsApp sur mon telephone »
ouvrirait WhatsApp sur Windows).
"""
from __future__ import annotations

import logging
import re

from core.config import reglage
from core.mobile_adb import Adb, ErreurMobile
from core.registre import outil
from core.resultat import ResultatOutil
from core.util import sans_accents

LOG = logging.getLogger("jarvis.tools.mobile")
_ADB = None


def _adb() -> Adb:
    global _ADB
    if _ADB is None:
        _ADB = Adb(adb=str(reglage("mobile.adb_chemin", "") or "") or None, appareil=str(reglage("mobile.appareil", "") or ""),
                   alias=reglage("mobile.apps", {}) or {})
    return _ADB


def _ko(exc, erreur="mobile"):
    return ResultatOutil(str(exc), succes=False, erreur=erreur)


def _gerer(fonction):
    """Toute erreur ADB devient une reponse parlee, jamais une exception qui coupe le tour."""
    def enveloppe(*a, **kw):
        try:
            return fonction(*a, **kw)
        except ErreurMobile as exc:
            return _ko(exc)
        except Exception as exc:                                               # noqa: BLE001
            LOG.exception("outil mobile")
            return _ko(f"Erreur inattendue avec le telephone : {exc}", "exception")
    enveloppe.__name__, enveloppe.__doc__ = fonction.__name__, fonction.__doc__
    return enveloppe


def _annonce(texte):
    return lambda args: texte.format(**{k: (v if v is not None else "") for k, v in args.items()})


_SCHEMA_VIDE = {"type": "object", "properties": {}}


@outil(nom="mobile_statut", description="Etat du telephone Android : batterie, charge, ecran, signal, app au premier plan. "
       "Pour « quelle batterie a mon telephone ? ».", parametres=_SCHEMA_VIDE)
@_gerer
def mobile_statut():
    s = _adb().statut()
    morceaux = [f"{s['modele']} sous Android {s['android']}"]
    if s.get("niveau") is not None:
        morceaux.append(f"batterie {s['niveau']} %" + (" en charge" if s.get("en_charge") else ""))
    morceaux.append("écran allumé" if s.get("ecran_allume") else "écran éteint" if s.get("ecran_allume") is False else "écran inconnu")
    sig = s.get("signal") or {}
    if "wifi_rssi_dbm" in sig:
        morceaux.append(f"Wi-Fi {sig['wifi_rssi_dbm']} dBm")
    if "mobile_niveau_0_4" in sig:
        morceaux.append(f"réseau mobile niveau {sig['mobile_niveau_0_4']}/4 (approximatif)")
    return ResultatOutil("Téléphone : " + ", ".join(morceaux) + ".", succes=True, verifie=True, details=s)


@outil(nom="mobile_lancer_application", description="Lance une application sur le TELEPHONE Android (WhatsApp, YouTube, Chrome, "
       "Parametres...). Seulement quand la demande dit telephone/portable.",
       parametres={"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]})
@_gerer
def mobile_lancer_application(nom: str):
    r = _adb().lancer_app(nom)
    if r["verifie"]:
        return ResultatOutil(f"{nom} est ouverte sur le téléphone.", succes=True, verifie=True, details=r)
    return ResultatOutil(f"J'ai lancé {nom} sur le téléphone mais je n'ai pas pu confirmer qu'elle est à l'écran "
                         "(téléphone verrouillé ?).", succes=True, verifie=False, details=r)


@outil(nom="mobile_ouvrir_url", description="Ouvre une adresse web (http/https) dans le navigateur du TELEPHONE.",
       parametres={"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]})
@_gerer
def mobile_ouvrir_url(url: str):
    _adb().ouvrir_url(url)
    return ResultatOutil("Lien envoyé au téléphone.", succes=True, verifie=False)


@outil(nom="mobile_touche", description="Appuie sur une touche du telephone : accueil, retour, recents, volume_plus, volume_moins, "
       "muet, reveil, veille, entree, supprimer.",
       parametres={"type": "object", "properties": {"touche": {"type": "string"}}, "required": ["touche"]})
@_gerer
def mobile_touche(touche: str):
    _adb().touche(touche)
    return ResultatOutil(f"Touche « {touche} » envoyée au téléphone.", succes=True, verifie=False)


@outil(nom="mobile_lire_media", description="Controle la lecture audio/video du TELEPHONE : lecture, pause, suivant, precedent, "
       "stop, volume_plus, volume_moins, muet.",
       parametres={"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]})
@_gerer
def mobile_lire_media(action: str):
    cle = _adb().media(action)
    return ResultatOutil(f"Commande média « {cle} » envoyée au téléphone.", succes=True, verifie=False)


@outil(nom="mobile_defiler", description="Fait defiler l'ecran du telephone (sens : haut, bas, gauche, droite).",
       parametres={"type": "object", "properties": {"sens": {"type": "string"}}, "required": ["sens"]})
@_gerer
def mobile_defiler(sens: str):
    _adb().defiler(sens)
    return ResultatOutil(f"Défilement {sens} envoyé.", succes=True, verifie=False)


@outil(nom="mobile_envoyer_notification", description="Affiche une notification sur l'ecran du TELEPHONE (titre + message).",
       parametres={"type": "object", "properties": {"titre": {"type": "string"}, "message": {"type": "string"}},
                   "required": ["titre", "message"]})
@_gerer
def mobile_envoyer_notification(titre: str, message: str):
    _adb().notification(titre, message)
    return ResultatOutil("Notification envoyée au téléphone.", succes=True, verifie=False)


# ------------------------------------------------------------------------------- N2 : lire / agir
@outil(nom="mobile_toucher", confirmation=True,
       annonce=_annonce("Je touche « {cible} » sur ton téléphone. Tu confirmes ?"),
       description="Touche un element de l'ecran du TELEPHONE par son texte (« Envoyer », « OK »...) ou par coordonnees x,y.",
       parametres={"type": "object", "properties": {"cible": {"type": "string"}, "x": {"type": "integer"},
                                                      "y": {"type": "integer"}}})
@_gerer
def mobile_toucher(cible: str = "", x: int | None = None, y: int | None = None):
    if cible:
        r = _adb().toucher_texte(cible)
        return ResultatOutil(f"J'ai touché « {r['libelle']} »" + ("." if r["verifie"] else ", sans changement visible à l'écran."),
                             succes=True, verifie=r["verifie"], details=r)
    if x is None or y is None:
        return _ko("Dis-moi quoi toucher : un texte ou des coordonnées.", "arguments")
    _adb().appuyer(x, y)
    return ResultatOutil(f"Touché en ({x}, {y}).", succes=True, verifie=False)


@outil(nom="mobile_taper_texte", confirmation=True, annonce=_annonce("Je tape « {texte} » sur ton téléphone. Tu confirmes ?"),
       description="Saisit du texte (ASCII, une ligne) dans le champ actif du TELEPHONE.",
       parametres={"type": "object", "properties": {"texte": {"type": "string"}}, "required": ["texte"]})
@_gerer
def mobile_taper_texte(texte: str):
    _adb().taper_texte(texte)
    return ResultatOutil("Texte saisi sur le téléphone.", succes=True, verifie=False)


@outil(nom="mobile_lire_ecran", confirmation=True, annonce=_annonce("Je lis l'écran de ton téléphone. Tu confirmes ?"),
       description="Lit les textes et boutons visibles a l'ecran du TELEPHONE (arbre d'interface).",
       parametres=_SCHEMA_VIDE)
@_gerer
def mobile_lire_ecran():
    els = _adb().interface()
    textes = []
    for e in els:
        t = (e["texte"] or e["desc"]).strip()
        if t and t not in textes:
            textes.append(t)
    return ResultatOutil("À l'écran : " + " ; ".join(textes[:40]) + ".", succes=True, verifie=True, details={"elements": len(els)})


@outil(nom="mobile_capture_ecran", confirmation=True, annonce=_annonce("Je capture l'écran de ton téléphone. Tu confirmes ?"),
       description="Capture l'ecran du TELEPHONE et l'enregistre sur le PC (logs/mobile/).", parametres=_SCHEMA_VIDE)
@_gerer
def mobile_capture_ecran():
    f = _adb().capture_ecran()
    return ResultatOutil(f"Capture enregistrée : {f.name}.", succes=True, verifie=True, details={"chemin": str(f)})


@outil(nom="mobile_lire_notifications", confirmation=True,
       annonce=_annonce("Je lis les notifications de ton téléphone. Tu confirmes ?"),
       description="Lit les notifications en cours sur le TELEPHONE (application, titre, texte).", parametres=_SCHEMA_VIDE)
@_gerer
def mobile_lire_notifications():
    notifs = _adb().notifications()
    if not notifs:
        return ResultatOutil("Aucune notification sur le téléphone.", succes=True, verifie=True, details={"notifications": []})
    lignes = [f"{n['paquet'].split('.')[-1]} : {n['titre']} — {n['texte']}".strip(" —") for n in notifs[:8]]
    return ResultatOutil(f"{len(notifs)} notification(s) : " + " ; ".join(lignes) + ".", succes=True, verifie=True,
                         details={"notifications": notifs})


@outil(nom="mobile_position", confirmation=True, annonce=_annonce("Je lis la position de ton téléphone. Tu confirmes ?"),
       description="Derniere position connue du TELEPHONE (latitude/longitude).", parametres=_SCHEMA_VIDE)
@_gerer
def mobile_position():
    p = _adb().position()
    if not p:
        return ResultatOutil("Je ne trouve pas de position récente (localisation désactivée ?).", succes=False, erreur="introuvable")
    return ResultatOutil(f"Dernière position connue : {p['latitude']:.5f}, {p['longitude']:.5f} (source {p['source']}).",
                         succes=True, verifie=True, details=p)


@outil(nom="mobile_photo", confirmation=True, annonce=_annonce("Je prends une photo avec la caméra de ton téléphone. Tu confirmes ?"),
       description="Prend une photo avec la camera du TELEPHONE et la rapatrie sur le PC (logs/mobile/).", parametres=_SCHEMA_VIDE)
@_gerer
def mobile_photo():
    f = _adb().photo()
    return ResultatOutil(f"Photo prise et copiée sur le PC : {f.name}.", succes=True, verifie=True, details={"chemin": str(f)})


# ------------------------------------------------------------------------------- routage vocal
_CUE = re.compile(r"\b(?:sur|de|du|a|au|avec|dans|vers) (?:mon|ma|le|la|ce) (?:telephone|tel|portable|smartphone|mobile)\b"
                  r"|\b(?:mon|ton) (?:telephone|portable|smartphone)\b|\bsur le tel\b")
_FIN_CUE = r"(?:\s+(?:sur|de|du|a|au|avec|dans|vers)\s+(?:mon|ma|le|la|ce)\s+(?:telephone|tel|portable|smartphone|mobile))"


def router_mobile(phrase, piece=""):
    """Route deterministe des phrases qui visent le TELEPHONE (cue obligatoire) ; None sinon."""
    n = " ".join(re.sub(r"[^a-z0-9']+", " ", sans_accents(str(phrase or "").lower())).split())
    if not n or not _CUE.search(n):
        return None
    sans = re.sub(_FIN_CUE, "", n).strip()
    if re.search(r"\bbatterie\b|\bquel niveau\b|\betat de (?:mon|ton) (?:telephone|portable)", n):
        return "mobile_statut", {}
    if re.search(r"\bnotifications?\b", n) and re.search(r"\b(lis|lire|montre|quelles?|affiche|y a t il)\b", n):
        return "mobile_lire_notifications", {}
    if re.search(r"\b(photo|selfie)\b", n) and re.search(r"\b(prends|prend|fais|fait|prendre)\b", n):
        return "mobile_photo", {}
    if re.search(r"\bcapture\b|\bscreenshot\b|\bcapture d ecran\b", n):
        return "mobile_capture_ecran", {}
    if re.search(r"\b(ou est|position|localise)\b", n) and re.search(r"\b(telephone|portable|tel)\b", n):
        return "mobile_position", {}
    if re.search(r"\blis (?:l )?ecran\b|\bqu est ce qu il y a a l ecran\b", n):
        return "mobile_lire_ecran", {}
    m = re.match(r"^(?:peux tu |pourrais tu |jarvis )?(?:ouvre|lance|demarre|ouvrir|lancer)\s+(?:l |la |le |les )?(.+)$", sans)
    if m and m.group(1).strip():
        return "mobile_lancer_application", {"nom": m.group(1).strip()}
    for mot, action in (("pause", "pause"), ("suivante?", "suivant"), ("precedente?", "precedent"), ("lecture", "lecture"),
                        ("reprends", "lecture"), ("stop", "stop")):
        if re.search(rf"\b{mot}\b", sans):
            return "mobile_lire_media", {"action": action}
    if re.search(r"\b(monte|augmente)\b.*\bvolume\b|\bvolume (?:plus|haut)\b", sans):
        return "mobile_lire_media", {"action": "volume_plus"}
    if re.search(r"\b(baisse|diminue)\b.*\bvolume\b|\bvolume (?:moins|bas)\b", sans):
        return "mobile_lire_media", {"action": "volume_moins"}
    for mot, touche in (("retour", "retour"), ("accueil", "accueil"), ("recents", "recents")):
        if re.search(rf"\b{mot}\b", sans):
            return "mobile_touche", {"touche": touche}
    m = re.search(r"\bdefile\b.*\b(haut|bas|gauche|droite)\b", sans)
    if m:
        return "mobile_defiler", {"sens": m.group(1)}
    return None
