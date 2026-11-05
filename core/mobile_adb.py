"""Controle d'un telephone Android depuis le PC par ADB (Android Debug Bridge) -- sans installer d'app sur le telephone.

Pourquoi ADB : c'est l'outil officiel et gratuit de Google ; en « debogage sans fil » (Android 11+) le PC pilote le
telephone par le Wi-Fi comme avec un cable : lancer une app, toucher/balayer/taper, lire l'interface, capturer l'ecran,
lire les notifications, prendre une photo. Aucun Visual C++, aucune compilation. Voir docs/mobile_android.md.

Principes :
- jamais de shell cote PC : ``adb`` est lance avec une LISTE d'arguments ; cote telephone chaque argument est protege
  par ``shlex.quote`` (pas d'injection depuis un nom d'app ou un texte dicte) ;
- un resultat n'est « verifie » que s'il a ete CONSTATE (app au premier plan, fichier photo nouveau...) ;
- toutes les analyses de sorties (``dumpsys`` ...) sont des fonctions pures testees sur des sorties types ; elles sont
  « au mieux » : Android varie selon les marques (Tecno/HiOS...), une valeur introuvable est dite introuvable, jamais inventee.
"""
from __future__ import annotations

import logging
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

LOG = logging.getLogger("jarvis.mobile")

ALIAS_APPS = {
    "whatsapp": "com.whatsapp", "youtube": "com.google.android.youtube", "chrome": "com.android.chrome",
    "gmail": "com.google.android.gm", "maps": "com.google.android.apps.maps", "google maps": "com.google.android.apps.maps",
    "facebook": "com.facebook.katana", "messenger": "com.facebook.orca", "instagram": "com.instagram.android",
    "tiktok": "com.zhiliaoapp.musically", "telegram": "org.telegram.messenger", "spotify": "com.spotify.music",
    "netflix": "com.netflix.mediaclient", "snapchat": "com.snapchat.android", "twitter": "com.twitter.android",
    "x": "com.twitter.android", "play store": "com.android.vending", "photos": "com.google.android.apps.photos",
    "parametres": "com.android.settings", "reglages": "com.android.settings", "settings": "com.android.settings",
    "telephone": "com.google.android.dialer", "contacts": "com.google.android.contacts",
    "calculatrice": "com.google.android.calculator", "horloge": "com.google.android.deskclock",
}
TOUCHES = {"accueil": 3, "home": 3, "retour": 4, "back": 4, "recents": 187, "multitache": 187, "menu": 82,
           "veille": 223, "reveil": 224, "reveiller": 224, "power": 26, "volume_plus": 24, "volume_moins": 25,
           "muet": 164, "entree": 66, "supprimer": 67, "camera": 27,
           "play_pause": 85, "suivant": 87, "precedent": 88, "stop": 86}
MEDIA = {"lecture": "play_pause", "pause": "play_pause", "play": "play_pause", "play_pause": "play_pause",
         "suivant": "suivant", "next": "suivant", "precedent": "precedent", "previous": "precedent", "stop": "stop",
         "volume_plus": "volume_plus", "monter": "volume_plus", "volume_moins": "volume_moins", "baisser": "volume_moins",
         "muet": "muet"}


class ErreurMobile(RuntimeError):
    """Operation impossible ; le message est lisible a voix haute."""


# ------------------------------------------------------------------------------ analyses pures
def parser_batterie(texte: str) -> dict:
    def entier(cle):
        m = re.search(rf"^\s*{cle}:\s*(-?\d+)", texte, re.M)
        return int(m.group(1)) if m else None

    def booleen(cle):
        m = re.search(rf"^\s*{cle}:\s*(true|false)", texte, re.M | re.I)
        return m.group(1).lower() == "true" if m else None
    statut = entier("status")
    return {"niveau": entier("level"), "en_charge": (statut in (2, 5)) if statut is not None else
            (True if (booleen("AC powered") or booleen("USB powered")) else None),
            "temperature_c": (entier("temperature") / 10 if entier("temperature") is not None else None)}


def parser_focus(texte: str) -> str:
    """Paquet de l'app au premier plan (``mCurrentFocus`` / ``ResumedActivity``), '' si inconnu."""
    for motif in (r"mCurrentFocus=Window\{[^}]*\s([\w.]+)/[\w.$]+", r"mResumedActivity:.*?\s([\w.]+)/[\w.$]+",
                  r"ResumedActivity:.*?\s([\w.]+)/[\w.$]+"):
        m = re.search(motif, texte)
        if m:
            return m.group(1)
    return ""


def parser_ecran_allume(texte: str):
    m = re.search(r"mWakefulness=(\w+)", texte)
    return (m.group(1) == "Awake") if m else None


def parser_position(texte: str):
    m = re.search(r"Location\[(\w+) (-?\d+\.\d+),\s*(-?\d+\.\d+)(?: hAcc=(\d+(?:\.\d+)?))?", texte)
    if not m:
        return None
    return {"source": m.group(1), "latitude": float(m.group(2)), "longitude": float(m.group(3)),
            "precision_m": float(m.group(4)) if m.group(4) else None}


def parser_signal(texte: str) -> dict:
    res = {}
    m = re.search(r"rssi=(-?\d+)", texte)
    if m:
        res["wifi_rssi_dbm"] = int(m.group(1))
    m = re.search(r"mSignalStrength=.*?\blevel=(\d)", texte, re.S) or re.search(r"\blevel=(\d) ", texte)
    if m:
        res["mobile_niveau_0_4"] = int(m.group(1))
    return res


def _valeur_extra(brut: str) -> str:
    brut = brut.strip()
    m = re.match(r"^(?:\w*String\w*|CharSequence) \((.*)\)$", brut, re.S)
    return (m.group(1) if m else brut).strip()


def parser_notifications(texte: str, limite=30) -> list[dict]:
    """[{paquet, titre, texte}] depuis ``dumpsys notification --noredact`` (Android 12 : ``android.title=...``)."""
    res = []
    morceaux = re.split(r"(?m)^\s*NotificationRecord\(", texte)
    for bloc in morceaux[1:]:
        pkg = re.search(r"\bpkg=([\w.]+)", bloc)
        titre = re.search(r"android\.title=(.*)", bloc)
        corps = re.search(r"android\.text=(.*)", bloc) or re.search(r"android\.bigText=(.*)", bloc)
        if not pkg or not (titre or corps):
            continue
        res.append({"paquet": pkg.group(1), "titre": _valeur_extra(titre.group(1)) if titre else "",
                    "texte": _valeur_extra(corps.group(1)) if corps else ""})
        if len(res) >= limite:
            break
    return res


def parser_ui(xml: str) -> list[dict]:
    """Elements de l'ecran (uiautomator) : texte, description, cliquable, centre (x, y)."""
    debut = xml.find("<?xml")
    fin = xml.rfind("</hierarchy>")
    if debut < 0 or fin < 0:
        return []
    import xml.etree.ElementTree as ET
    try:
        racine = ET.fromstring(xml[debut:fin + len("</hierarchy>")])
    except ET.ParseError:
        return []
    res = []
    for n in racine.iter("node"):
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds", ""))
        if not m:
            continue
        x1, y1, x2, y2 = map(int, m.groups())
        res.append({"texte": n.get("text", ""), "desc": n.get("content-desc", ""), "id": n.get("resource-id", ""),
                    "paquet": n.get("package", ""), "cliquable": n.get("clickable") == "true",
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2, "largeur": x2 - x1, "hauteur": y2 - y1})
    return res


def trouver_element(elements: list[dict], cible: str):
    """Meilleur element dont le texte/la description correspond (exact > commence par > contient ; cliquable prefere)."""
    from core.util import sans_accents
    c = sans_accents(cible.lower()).strip()
    meilleur, score_max = None, 0
    for e in elements:
        for champ in (e["texte"], e["desc"]):
            t = sans_accents(champ.lower()).strip()
            if not t:
                continue
            s = 3 if t == c else 2 if t.startswith(c) else 1 if c in t else 0
            if s and e["cliquable"]:
                s += 0.5
            if s > score_max:
                meilleur, score_max = e, s
    return meilleur


def trouver_paquet(sortie_pm: str, nom: str, alias=None) -> str:
    """Nom d'app dicte -> paquet Android : alias connus/configures, sinon recherche dans ``pm list packages``."""
    from core.util import sans_accents
    n = sans_accents(str(nom).lower()).strip()
    n = re.sub(r"^(l'|la |le |les |l )", "", n).strip()
    table = {**ALIAS_APPS, **{sans_accents(k.lower()): v for k, v in (alias or {}).items()}}
    if n in table:
        return table[n]
    if re.fullmatch(r"[a-z][\w]*(\.[\w]+)+", n):                        # deja un nom de paquet
        return n
    jetons = [t for t in re.split(r"[^a-z0-9]+", n) if len(t) >= 3]
    if not jetons:
        return ""
    candidats = [l.split(":", 1)[1].strip() for l in sortie_pm.splitlines() if l.startswith("package:")]
    ok = [p for p in candidats if all(j in p.lower() for j in jetons)]
    return min(ok, key=len) if ok else ""


# ------------------------------------------------------------------------------ pilote ADB
class Adb:
    """Une session ADB vers UN appareil. ``runner`` et ``dormir`` sont injectables (tests : faux telephone)."""

    def __init__(self, adb=None, appareil="", runner=subprocess.run, dormir=time.sleep, dossier=None, alias=None):
        self.adb = adb or shutil.which("adb") or "adb"
        self.appareil = appareil or ""
        self._run, self._dormir = runner, dormir
        self.dossier = Path(dossier) if dossier else Path(__file__).resolve().parent.parent / "logs" / "mobile"
        self.alias = alias or {}

    # -- bas niveau ---------------------------------------------------------------------------------
    def _cmd(self, *args):
        base = [self.adb]
        if self.appareil:
            base += ["-s", self.appareil]
        return base + [str(a) for a in args]

    def brut(self, *args, timeout=30, binaire=False):
        """Lance adb (liste d'arguments). Renvoie (rc, stdout, stderr) ; stdout en bytes si ``binaire``."""
        try:
            r = self._run(self._cmd(*args), capture_output=True, timeout=timeout)
        except FileNotFoundError:
            raise ErreurMobile("ADB est introuvable : installe les « platform-tools » Android (voir docs/mobile_android.md) "
                               "ou renseigne mobile.adb_chemin.") from None
        except subprocess.TimeoutExpired:
            raise ErreurMobile("Le telephone ne repond pas (delai depasse).") from None
        out, err = r.stdout or b"", r.stderr or b""
        if not binaire:
            out = out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)
        err = err.decode("utf-8", "replace") if isinstance(err, bytes) else str(err)
        return r.returncode, out, err

    def shell(self, *args, timeout=30) -> str:
        """Commande cote telephone ; chaque argument est protege (shlex.quote). Leve ErreurMobile si adb echoue."""
        ligne = " ".join(shlex.quote(str(a)) for a in args)
        rc, out, err = self.brut("shell", ligne, timeout=timeout)
        if rc != 0:
            raise ErreurMobile(self._expliquer(err or out))
        return out

    @staticmethod
    def _expliquer(err: str) -> str:
        e = (err or "").lower()
        if "unauthorized" in e:
            return "Le telephone n'a pas autorise ce PC : accepte la fenetre « Autoriser le debogage USB » sur le telephone."
        if "no devices" in e or "not found" in e or "offline" in e or "more than one device" in e:
            return ("Aucun telephone joignable : active le debogage sans fil, verifie que le PC et le telephone sont "
                    "sur le meme Wi-Fi, puis relance l'appairage (docs/mobile_android.md).")
        return f"Erreur ADB : {err.strip()[:200]}"

    # -- connexion ------------------------------------------------------------------------------------
    def appareils(self) -> list[tuple[str, str]]:
        rc, out, err = self.brut("devices", timeout=15)
        if rc != 0:
            raise ErreurMobile(self._expliquer(err))
        return [(l.split()[0], l.split()[1]) for l in out.splitlines()[1:] if len(l.split()) >= 2]

    def connecter(self, adresse: str) -> str:
        if not re.fullmatch(r"[\w.\-]+:\d{2,5}", adresse or ""):
            raise ErreurMobile("Adresse invalide : attendu « adresse_ip:port ».")
        rc, out, err = self.brut("connect", adresse, timeout=20)
        if rc != 0 or "connected" not in out.lower() or "cannot" in out.lower() or "failed" in out.lower():
            raise ErreurMobile(self._expliquer(out + err) if "unauthorized" in (out + err).lower() else
                               f"Connexion impossible a {adresse} : {(out + err).strip()[:150]}")
        self.appareil = adresse
        return out.strip()

    def appairer(self, adresse: str, code: str) -> str:
        if not re.fullmatch(r"[\w.\-]+:\d{2,5}", adresse or "") or not re.fullmatch(r"\d{6}", code or ""):
            raise ErreurMobile("Appairage : adresse « ip:port » et code a 6 chiffres attendus.")
        rc, out, err = self.brut("pair", adresse, code, timeout=30)
        if "successfully paired" not in out.lower():
            raise ErreurMobile(f"Appairage refuse : {(out + err).strip()[:150]}")
        return out.strip()

    def assurer_connexion(self):
        """Verifie qu'un appareil est pret ; tente la reconnexion sur ``self.appareil`` (ip:port) sinon."""
        etats = dict(self.appareils())
        if self.appareil and etats.get(self.appareil) == "device":
            return
        if not self.appareil and len([e for e in etats.values() if e == "device"]) == 1:
            return
        if self.appareil and ":" in self.appareil:
            self.connecter(self.appareil)
            if dict(self.appareils()).get(self.appareil) == "device":
                return
        raise ErreurMobile(self._expliquer("no devices"))

    # -- lecture d'etat -------------------------------------------------------------------------------
    def statut(self) -> dict:
        self.assurer_connexion()
        res = {"modele": self.shell("getprop", "ro.product.model").strip(),
               "android": self.shell("getprop", "ro.build.version.release").strip()}
        res.update(parser_batterie(self.shell("dumpsys", "battery")))
        res["ecran_allume"] = parser_ecran_allume(self.shell("dumpsys", "power"))
        signal = {}
        for cmd in (("dumpsys", "wifi"), ("dumpsys", "telephony.registry")):
            try:
                signal.update(parser_signal(self.shell(*cmd, timeout=20)))
            except ErreurMobile:
                pass
        res["signal"] = signal
        res["app_au_premier_plan"] = self.app_au_premier_plan()
        return res

    def app_au_premier_plan(self) -> str:
        try:
            return parser_focus(self.shell("dumpsys", "window", timeout=20)) or ""
        except ErreurMobile:
            return ""

    def position(self):
        self.assurer_connexion()
        return parser_position(self.shell("dumpsys", "location", timeout=20))

    def notifications(self, limite=15) -> list[dict]:
        self.assurer_connexion()
        return parser_notifications(self.shell("dumpsys", "notification", "--noredact", timeout=30), limite)

    # -- actions --------------------------------------------------------------------------------------
    def reveiller(self):
        self.assurer_connexion()
        if parser_ecran_allume(self.shell("dumpsys", "power")) is not True:
            self.shell("input", "keyevent", 224)
            self._dormir(0.6)

    def lancer_app(self, nom: str) -> dict:
        """Lance une app par son nom. Renvoie {paquet, verifie, au_premier_plan}."""
        self.assurer_connexion()
        paquets = self.shell("pm", "list", "packages", "-3", timeout=30) if nom.lower().strip() not in ALIAS_APPS \
            and nom.lower().strip() not in {k.lower() for k in self.alias} else ""
        paquet = trouver_paquet(paquets, nom, self.alias)
        if not paquet and paquets:
            paquet = trouver_paquet(self.shell("pm", "list", "packages", timeout=30), nom, self.alias)
        if not paquet:
            raise ErreurMobile(f"Je ne trouve pas d'application « {nom} » sur le telephone.")
        self.reveiller()
        sortie = self.shell("monkey", "-p", paquet, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)
        if "no activities found" in sortie.lower() or "monkey aborted" in sortie.lower():
            raise ErreurMobile(f"« {nom} » ({paquet}) n'est pas installee ou ne peut pas etre lancee.")
        self._dormir(1.5)
        avant = self.app_au_premier_plan()
        return {"paquet": paquet, "au_premier_plan": avant, "verifie": avant == paquet}

    def ouvrir_url(self, url: str):
        if not re.match(r"^https?://", url or "", re.I):
            raise ErreurMobile("Seules les adresses http(s) sont ouvertes.")
        self.assurer_connexion()
        self.reveiller()
        self.shell("am", "start", "-a", "android.intent.action.VIEW", "-d", url)

    def touche(self, nom: str):
        code = TOUCHES.get(str(nom).lower().strip())
        if code is None:
            raise ErreurMobile(f"Touche inconnue : {nom}. Possibles : {', '.join(sorted(TOUCHES))}.")
        self.assurer_connexion()
        self.shell("input", "keyevent", code)

    def media(self, action: str):
        cle = MEDIA.get(str(action).lower().strip())
        if not cle:
            raise ErreurMobile(f"Action media inconnue : {action}. Possibles : {', '.join(sorted(MEDIA))}.")
        self.touche(cle)
        return cle

    def appuyer(self, x: int, y: int):
        self.assurer_connexion()
        self.shell("input", "tap", int(x), int(y))

    def balayer(self, x1, y1, x2, y2, duree_ms=300):
        self.assurer_connexion()
        self.shell("input", "swipe", int(x1), int(y1), int(x2), int(y2), int(duree_ms))

    def defiler(self, sens: str):
        """haut/bas/gauche/droite : geste de defilement au centre de l'ecran (1080x2400 par defaut, ajuste par la taille reelle)."""
        self.assurer_connexion()
        m = re.search(r"(\d+)x(\d+)", self.shell("wm", "size"))
        w, h = (int(m.group(1)), int(m.group(2))) if m else (720, 1600)
        gestes = {"bas": (w // 2, int(h * .7), w // 2, int(h * .3)), "haut": (w // 2, int(h * .3), w // 2, int(h * .7)),
                  "gauche": (int(w * .8), h // 2, int(w * .2), h // 2), "droite": (int(w * .2), h // 2, int(w * .8), h // 2)}
        if sens not in gestes:
            raise ErreurMobile("Sens possibles : haut, bas, gauche, droite.")
        self.shell("input", "swipe", *gestes[sens], 350)

    def taper_texte(self, texte: str):
        """Saisie dans le champ actif. ``input text`` ne gere que l'ASCII : le reste est refuse, pas tronque."""
        if not texte or not texte.isascii() or "\n" in texte:
            raise ErreurMobile("Je ne peux saisir que du texte ASCII sur une ligne (accents non supportes par ADB).")
        self.assurer_connexion()
        self.shell("input", "text", texte.replace(" ", "%s"))

    def interface(self) -> list[dict]:
        self.assurer_connexion()
        rc, out, err = self.brut("exec-out", "uiautomator", "dump", "/dev/tty", timeout=30)
        elements = parser_ui(out)
        if not elements:
            raise ErreurMobile("Je n'arrive pas a lire l'ecran (ecran verrouille, ou ecran protege).")
        return elements

    def toucher_texte(self, cible: str) -> dict:
        """Touche l'element dont le texte correspond (« Envoyer », « OK »...). Verifie que l'ecran a change."""
        el = trouver_element(self.interface(), cible)
        if el is None:
            raise ErreurMobile(f"Je ne vois pas « {cible} » a l'ecran du telephone.")
        avant = {(e["texte"], e["desc"]) for e in self.interface()}
        self.appuyer(el["x"], el["y"])
        self._dormir(0.8)
        try:
            apres = {(e["texte"], e["desc"]) for e in self.interface()}
        except ErreurMobile:
            apres = set()
        return {"x": el["x"], "y": el["y"], "libelle": el["texte"] or el["desc"], "verifie": apres != avant}

    def capture_ecran(self) -> Path:
        self.assurer_connexion()
        rc, out, err = self.brut("exec-out", "screencap", "-p", timeout=30, binaire=True)
        if rc != 0 or not out.startswith(b"\x89PNG"):
            raise ErreurMobile("La capture d'ecran a echoue (ecran verrouille ou application protegee).")
        self.dossier.mkdir(parents=True, exist_ok=True)
        f = self.dossier / f"capture_{time.strftime('%Y%m%d_%H%M%S')}.png"
        f.write_bytes(out)
        return f

    def photo(self, dossier_dcim="/sdcard/DCIM/Camera") -> Path:
        """Photo avec l'app Camera du telephone, rapatriee sur le PC. « Verifie » = nouveau fichier constate."""
        self.assurer_connexion()
        self.reveiller()

        def dernier():
            try:
                return self.shell("ls", "-t", dossier_dcim, timeout=20).split()[:1]
            except ErreurMobile:
                return []
        avant = dernier()
        self.shell("am", "start", "-a", "android.media.action.STILL_IMAGE_CAMERA")
        self._dormir(2.5)
        self.shell("input", "keyevent", 27)
        self._dormir(2.5)
        apres = dernier()
        if not apres or apres == avant:
            raise ErreurMobile("Je n'ai pas pu constater de nouvelle photo (autorise la camera, deverrouille le telephone).")
        self.dossier.mkdir(parents=True, exist_ok=True)
        local = self.dossier / f"photo_{time.strftime('%Y%m%d_%H%M%S')}_{Path(apres[0]).name}"
        rc, out, err = self.brut("pull", f"{dossier_dcim}/{apres[0]}", str(local), timeout=60)
        if rc != 0 or not local.exists():
            raise ErreurMobile(f"Photo prise mais non rapatriee : {(out + err).strip()[:150]}")
        return local

    def notification(self, titre: str, message: str):
        """Poste une notification sur le telephone (``cmd notification post``)."""
        self.assurer_connexion()
        self.shell("cmd", "notification", "post", "-S", "bigtext", "-t", titre[:80], "jarvis", message[:400])
