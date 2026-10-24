"""Controle du PC sans vision : lancer une appli, activer une fenetre, raccourcis clavier,
saisie de texte, clic sur un bouton PAR SON NOM (UI Automation), recherche dans une appli.

Windows seulement (ctypes + PowerShell, aucune dependance ni Visual C++). Complete
capture_screen/cliquer_ecran (clic « a l'oeil ») : ici Jarvis agit par le CLAVIER et par les
NOMS des controles, bien plus fiable et sans modele de vision.
Securite : jamais de mot de passe ni de paiement (consigne), Ctrl+Alt+Suppr refuse.
Config (config.yaml) : controle_pc.recherche_raccourcis {appli: "ctrl+l"}.
"""
from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import shutil
import subprocess
import time
import unicodedata

from core.config import reglage
from core.registre import outil
from core.resultat import ResultatOutil, est_echec
from ctypes import wintypes

# ============================================================
# CONFIGURATION DES API WINDOWS
# ============================================================

_WINDLL = getattr(ctypes, "windll", None)      # absent hors Windows (tests, CI)
EST_WINDOWS = _WINDLL is not None
user32 = _WINDLL.user32 if EST_WINDOWS else None
kernel32 = _WINDLL.kernel32 if EST_WINDOWS else None


def _exiger_windows():
    """Leve une erreur claire (au lieu d'un AttributeError obscur) hors Windows."""
    if not EST_WINDOWS:
        raise OSError("Le controle du PC ne fonctionne que sous Windows.")


if EST_WINDOWS:
    # Signatures explicites : sans elles, ctypes tronque les HWND 64 bits.
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL


LOG = logging.getLogger("jarvis.controle_pc")

_VK = {"ctrl": 0x11, "control": 0x11, "controle": 0x11, "shift": 0x10, "maj": 0x10, "alt": 0x12,
       "win": 0x5B, "windows": 0x5B, "enter": 0x0D, "entree": 0x0D, "entrer": 0x0D, "retour": 0x0D,
       "esc": 0x1B, "echap": 0x1B, "escape": 0x1B, "tab": 0x09, "tabulation": 0x09, "space": 0x20,
       "espace": 0x20, "backspace": 0x08, "retourarriere": 0x08, "delete": 0x2E, "suppr": 0x2E,
       "up": 0x26, "haut": 0x26, "down": 0x28, "bas": 0x28, "left": 0x25, "gauche": 0x25,
       "right": 0x27, "droite": 0x27, "home": 0x24, "debut": 0x24, "end": 0x23, "fin": 0x23,
       "pageup": 0x21, "pagedown": 0x22}
_RACCOURCIS_RECHERCHE = {"spotify": "ctrl+l", "discord": "ctrl+k", "whatsapp": "ctrl+f",
                         "chrome": "ctrl+l", "firefox": "ctrl+l", "edge": "ctrl+l"}
_INTERDITES = {frozenset({0x11, 0x12, 0x2E})}          # Ctrl+Alt+Suppr


def _sa(s):
    return "".join(c for c in unicodedata.normalize("NFD", str(s or "").lower()) if unicodedata.category(c) != "Mn")


def analyser_combinaison(texte):
    """'ctrl+shift+t' -> [0x11, 0x10, 0x54]. ValueError si une touche est inconnue."""
    codes = []
    for brut in str(texte or "").replace(" plus ", "+").replace(" ", "+").split("+"):
        k = _sa(brut).strip()
        if not k:
            continue
        if k in _VK:
            codes.append(_VK[k])
        elif len(k) == 1 and k.isalnum():
            codes.append(ord(k.upper()))
        elif k[0] == "f" and k[1:].isdigit() and 1 <= int(k[1:]) <= 12:
            codes.append(0x70 + int(k[1:]) - 1)
        else:
            raise ValueError(f"touche inconnue : {brut}")
    if not codes:
        raise ValueError("combinaison vide")
    return codes


def _appuyer(codes):
    u = ctypes.windll.user32
    for c in codes:
        u.keybd_event(c, 0, 0, 0)
    for c in reversed(codes):
        u.keybd_event(c, 0, 2, 0)


def _unites_utf16(ch):
    """Unites UTF-16 d'un caractere (2 pour un emoji) : SendInput/UNICODE en attend une par frappe."""
    brut = ch.encode("utf-16-le")
    return [int.from_bytes(brut[i:i + 2], "little") for i in range(0, len(brut), 2)]


def _ecrire(texte):
    """Saisie Unicode (accents, ponctuation, emoji) via SendInput, caractere par caractere.

    Leve OSError si Windows refuse l'injection (SendInput renvoie 0 : fenetre
    elevee au premier plan, UIPI...) : un echec ne doit JAMAIS passer pour une saisie reussie.
    """
    _exiger_windows()

    class KB(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                    ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

    class MS(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                    ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_size_t)]

    class UN(ctypes.Union):
        _fields_ = [("ki", KB), ("mi", MS)]

    class IN(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("u", UN)]

    def envoyer(vk, scan, flags):
        i = IN(1, UN(ki=KB(vk, scan, flags, 0, 0)))
        envoyes = ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(IN))
        if envoyes != 1:
            raise OSError("Windows a refuse la saisie (une fenetre administrateur est peut-etre au premier plan)")

    texte = str(texte).replace("\r\n", "\n").replace("\r", "\n")
    for ch in texte:
        if ch == "\n":
            _appuyer([0x0D])
        elif ch == "\t":
            _appuyer([0x09])
        else:
            for unite in _unites_utf16(ch):
                envoyer(0, unite, 0x0004)                       # KEYEVENTF_UNICODE
                envoyer(0, unite, 0x0004 | 0x0002)              # ... | KEYEVENTF_KEYUP
        time.sleep(0.004)


def _est_masquee(hwnd):
    """Fenetre « cloaked » (UWP suspendue, autre bureau virtuel) : visible pour Win32 mais pas a l'ecran."""
    try:
        v = ctypes.c_int(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(v), ctypes.sizeof(v))
        return bool(v.value)
    except Exception:
        return False


def _fenetres():
    """[(hwnd, titre, exe)] des fenetres visibles avec un titre (z-order : la plus haute d'abord)."""
    _exiger_windows()
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    res = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        if _est_masquee(hwnd):
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        u.GetWindowTextW(hwnd, buf, n + 1)
        pid = ctypes.c_ulong()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        exe = ""
        h = k.OpenProcess(0x1000, False, pid.value)       # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            p = ctypes.create_unicode_buffer(520)
            taille = ctypes.c_ulong(520)
            if k.QueryFullProcessImageNameW(h, 0, p, ctypes.byref(taille)):
                exe = os.path.basename(p.value).lower()
            k.CloseHandle(h)
        res.append((hwnd, buf.value, exe))
        return True

    u.EnumWindows(cb, 0)
    return res


def choisir_fenetre(fenetres, requete):
    """Meilleure fenetre pour « spotify », « bloc-notes »... (titre OU nom du .exe)."""
    q = _sa(requete).strip()
    if not q:
        return None
    for test in (lambda t, e: _sa(e).rsplit(".", 1)[0] == q,
                 lambda t, e: q in _sa(e), lambda t, e: _sa(t).startswith(q), lambda t, e: q in _sa(t)):
        for f in fenetres:
            if test(f[1], f[2]):
                return f
    return None


# Resultat de la DERNIERE activation de fenetre : True (premier plan constate),
# False (fenetre trouvee mais focus refuse), None (inconnu / pas de tentative).
_ETAT = {"focus": None}

_TERMINAUX = frozenset({"conemu64.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
                        "windowsterminal.exe", "wt.exe", "conhost.exe"})

_ALIAS_EXE = {
    "bloc-notes": "notepad.exe", "bloc notes": "notepad.exe", "blocnotes": "notepad.exe",
    "notepad": "notepad.exe", "chrome": "chrome.exe", "google chrome": "chrome.exe",
    "visual studio code": "code.exe", "vscode": "code.exe", "vs code": "code.exe", "code": "code.exe",
    "explorateur": "explorer.exe", "explorateur de fichiers": "explorer.exe",
    "terminal": "conemu64.exe", "cmd": "cmd.exe",
    "word": "winword.exe", "excel": "excel.exe", "powerpoint": "powerpnt.exe",
    "firefox": "firefox.exe", "edge": "msedge.exe", "microsoft edge": "msedge.exe",
    "paint": "mspaint.exe", "spotify": "spotify.exe", "discord": "discord.exe",
}


def _norm_fenetre(texte):
    """Minuscules, sans accents, tirets/underscores = espaces (« Bloc-notes » == « bloc notes »)."""
    t = unicodedata.normalize("NFKD", str(texte or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("\xa0", " ").casefold()
    t = re.sub(r"[\s\-‐-―_]+", " ", t)
    return t.strip()


def _trouver_fenetre(requete, fenetres=None):
    """Fenetre correspondant a `requete`, SANS l'activer (fonction pure : testable hors Windows).

    Priorites : 1. executable (exact ou alias connu) ; 2. titre exact ; 3. titre contenant la
    requete (terminaux exclus sauf demande explicite). La premiere est la plus haute dans le z-order.
    """
    requete_norm = _norm_fenetre(requete)
    if not requete_norm:
        return None
    fenetres = _fenetres() if fenetres is None else fenetres
    if requete_norm in {"terminal", "console", "invite de commandes", "powershell", "cmd"}:
        # Demande explicite d'un terminal : n'importe lequel (Windows Terminal, conhost, PowerShell...).
        return next((f for f in fenetres if str(f[2]).lower() in _TERMINAUX), None)
    cible_exe = _ALIAS_EXE.get(requete_norm) or _ALIAS_EXE.get(requete_norm.replace(" ", "-"))

    if cible_exe:
        trouvees = [f for f in fenetres if _norm_fenetre(f[2]) == _norm_fenetre(cible_exe)]
    else:
        trouvees = [f for f in fenetres
                    if _norm_fenetre(f[2]) in (requete_norm, requete_norm + ".exe")]
    if not trouvees:
        trouvees = [f for f in fenetres if _norm_fenetre(f[1]) == requete_norm]
    if not trouvees:
        explicite = requete_norm in {"terminal", "cmd", "powershell"}
        trouvees = [f for f in fenetres
                    if requete_norm in _norm_fenetre(f[1])
                    and (explicite or str(f[2]).lower() not in _TERMINAUX)]
    return trouvees[0] if trouvees else None


def _premier_plan_est(hwnd):
    """Vrai si `hwnd` (ou sa fenetre racine) est reellement la fenetre au premier plan."""
    try:
        actif = ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return False
    if not actif:
        return False
    if int(actif) == int(hwnd):
        return True
    try:
        racine = ctypes.windll.user32.GetAncestor
        return int(racine(actif, 2)) == int(racine(hwnd, 2))       # GA_ROOT
    except Exception:
        return False


def _mettre_au_premier_plan(hwnd, essais=3):
    """Met `hwnd` au premier plan ET verifie que Windows l'a accepte.

    SetForegroundWindow seul est souvent refuse (verrou de premier plan) : on restaure si
    minimisee, on rattache temporairement notre thread a celui de la fenetre active, puis on
    reverifie avec GetForegroundWindow. Pas de simulation de la touche Alt (elle active la barre
    de menus de l'application et avalerait la premiere frappe).
    """
    _exiger_windows()
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    for essai in range(max(1, essais)):
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)                                   # SW_RESTORE
        actif = u.GetForegroundWindow()
        tid_courant = k.GetCurrentThreadId()
        tid_actif = u.GetWindowThreadProcessId(actif, None) if actif else 0
        attache = False
        if tid_actif and tid_actif != tid_courant:
            attache = bool(u.AttachThreadInput(tid_courant, tid_actif, True))
        try:
            u.BringWindowToTop(hwnd)
            u.SetForegroundWindow(hwnd)
        finally:
            if attache:
                u.AttachThreadInput(tid_courant, tid_actif, False)
        time.sleep(0.15 * (essai + 1))
        if _premier_plan_est(hwnd):
            return True
        try:
            u.SwitchToThisWindow(hwnd, True)                        # dernier recours (non documente)
        except Exception:
            pass
    return _premier_plan_est(hwnd)


def _activer(requete):
    """Trouve puis active une fenetre. Renvoie (hwnd, titre, exe) ou None si introuvable.

    Le resultat du focus est consigne dans _ETAT["focus"] (True / False) : une fenetre trouvee
    mais non activee n'est plus presentee comme un succes (lire _ETAT["focus"] apres l'appel).
    """
    _ETAT["focus"] = None
    f = _trouver_fenetre(requete)
    if not f:
        LOG.warning("Aucune fenetre correspondant a : %s", requete)
        return None
    ok = _mettre_au_premier_plan(f[0])
    _ETAT["focus"] = ok
    if not ok:
        LOG.warning("Fenetre trouvee mais activation NON confirmee : %s (%s), HWND=%s",
                    f[1], f[2], f[0])
    return f


_APPS = {"liste": None, "echec": 0.0}


def _apps_demarrer(forcer=False):
    """Applications du menu Demarrer (Get-StartApps, Store compris).

    Une liste vide ou une erreur n'est JAMAIS memorisee durablement (avant : `[]` cache a vie,
    donc « menu Demarrer vide » jusqu'au redemarrage). Echec = nouvel essai apres 60 s.
    """
    if _APPS["liste"] and not forcer:
        return _APPS["liste"]
    if not forcer and time.time() - _APPS["echec"] < 60:
        return []
    script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
              "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress")
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                           capture_output=True, timeout=25,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        brut = json.loads(r.stdout.decode("utf-8-sig", "replace").strip() or "[]")
        liste = brut if isinstance(brut, list) else [brut]
        liste = [a for a in liste if isinstance(a, dict) and a.get("Name") and a.get("AppID")]
    except Exception as exc:
        LOG.warning("Get-StartApps indisponible : %s", exc)
        liste = []
    if liste:
        _APPS["liste"] = liste
    else:
        _APPS["echec"] = time.time()
        LOG.warning("Get-StartApps n'a renvoye aucune application (secours : executables connus / App Paths)")
    return liste


def _cle_app(texte):
    return _norm_fenetre(texte)


def choisir_app(apps, nom):
    q = _cle_app(nom)
    exact = [a for a in apps if _cle_app(a.get("Name")) == q]
    partiel = [a for a in apps if q and q in _cle_app(a.get("Name"))]
    return (exact or sorted(partiel, key=lambda a: len(a.get("Name", ""))) or [None])[0]


# Liste FERMEE d'utilitaires Windows integres, lancables sans menu Demarrer ni PowerShell.
_EXECUTABLES_INTEGRES = {
    "bloc notes": "notepad.exe", "notepad": "notepad.exe",
    "calculatrice": "calc.exe", "calculette": "calc.exe",
    "explorateur": "explorer.exe", "explorateur de fichiers": "explorer.exe",
    "paint": "mspaint.exe",
}


def _chemin_app_paths(nom_exe):
    """Chemin d'un .exe enregistre dans le registre Windows (App Paths), ou None."""
    if not re.fullmatch(r"[a-z0-9_.\-]{1,60}\.exe", nom_exe or ""):
        return None
    try:
        import winreg
    except ImportError:
        return None
    for racine in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(racine, rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{nom_exe}") as cle:
                chemin = winreg.QueryValueEx(cle, None)[0]
            chemin = os.path.expandvars(str(chemin).strip('"'))
            if os.path.isfile(chemin):
                return chemin
        except OSError:
            continue
    return None


def _lancer_connu(nom):
    """Secours quand Get-StartApps ne trouve rien : utilitaires integres, App Paths, PATH.

    Le nom vient du LLM : il ne sert JAMAIS a construire une ligne de commande. Seuls sont lances
    un executable de la liste fermee ou un .exe que Windows a lui-meme enregistre (App Paths).
    """
    q = _cle_app(nom)
    exe = _EXECUTABLES_INTEGRES.get(q)
    if exe:
        subprocess.Popen([exe])
        return nom
    candidat = _ALIAS_EXE.get(q) or (re.sub(r"[^a-z0-9]+", "", q) + ".exe" if q else "")
    chemin = _chemin_app_paths(candidat) or (shutil.which(candidat) if candidat else None)
    if chemin:
        subprocess.Popen([chemin])
        return nom
    return None


def _lancer(nom):
    """Lance une appli (utilitaire integre, menu Demarrer Store compris, App Paths). Renvoie son nom ou None."""
    q = _cle_app(nom)
    if q in _EXECUTABLES_INTEGRES:                      # pas besoin de PowerShell pour le Bloc-notes
        return _lancer_connu(nom)
    app = choisir_app(_apps_demarrer(), nom)
    if app:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"])
        return app["Name"]
    return _lancer_connu(nom)


def _attendre_fenetre(nom, delai=12.0):
    """Attend l'apparition (ET l'activation) de la fenetre de `nom`. Renvoie la fenetre ou None."""
    fin = time.time() + delai
    while True:
        f = _activer(nom)
        if f:
            return f
        if time.time() >= fin:
            return None
        time.sleep(0.5)


def _resultat_fenetre(nom, f, deja_ouverte):
    focus = _ETAT["focus"]
    details = {"hwnd": int(f[0]), "titre": f[1], "executable": f[2], "focus": focus}
    if focus is False:
        return ResultatOutil(
            f"{nom} est ouvert, mais je n'arrive pas à le mettre au premier plan.",
            succes=False, verifie=True, details=details, erreur="focus")
    return ResultatOutil(f"{nom} est au premier plan." if deja_ouverte else f"{nom} est ouvert.",
                         succes=True, verifie=(focus is True), details=details)


def verifier_ouverture(nom, delai=8.0, requete=None, strict=True):
    """Apres un lancement « a l'aveugle » (os.startfile...), CONSTATE la fenetre. Jamais d'exception.

    requete : nom de recherche de la fenetre si different de `nom` (ex. « notepad.exe »).
    strict  : fenetre absente = echec (utilitaires Windows). Non strict = « lance, pas encore vu »
              (jeux/launchers lents : on ne pretend ni le succes verifie ni l'echec).
    """
    try:
        f = _attendre_fenetre(requete or nom, delai)
    except Exception as exc:                                   # hors Windows, API indisponible
        LOG.info("verification de la fenetre impossible : %s", exc)
        return ResultatOutil(f"{nom} lancé (je ne peux pas vérifier la fenêtre).", succes=True, verifie=False)
    if not f:
        return ResultatOutil(f"J'ai lancé {nom}, mais je ne vois pas sa fenêtre apparaître.",
                             succes=not strict, verifie=strict, erreur="fenetre_absente")
    return _resultat_fenetre(nom, f, deja_ouverte=False)


# ------------------------------------------------------------------ outils
@outil(
    nom="lancer_application_pc",
    description="Lance N'IMPORTE QUELLE application installee (Bloc-notes, Spotify, Discord, VS Code, Word, "
                "Steam...) par son nom, puis la met au premier plan ET verifie que sa fenetre est bien "
                "la. Pour « ouvre Spotify », « ouvre le Bloc-notes ». Si elle est deja ouverte, elle est "
                "simplement activee. Pour un SITE web, utilise browser_open.",
    parametres={"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]},
    mcp_expose=False,
)
def lancer_application_pc(nom: str) -> str:
    f = _activer(nom)
    if f:
        return _resultat_fenetre(nom, f, deja_ouverte=True)
    lance = _lancer(nom)
    if not lance:
        return ResultatOutil(f"Je ne trouve pas d'application « {nom} » sur ce PC.",
                             succes=False, erreur="introuvable")
    f = _attendre_fenetre(nom)
    if not f and _cle_app(lance) != _cle_app(nom):
        f = _attendre_fenetre(lance, 4.0)
    if not f:
        return ResultatOutil(f"J'ai lancé {lance}, mais je ne vois pas sa fenêtre apparaître.",
                             succes=False, verifie=True, erreur="fenetre_absente", details={"lance": lance})
    return _resultat_fenetre(lance, f, deja_ouverte=False)


@outil(
    nom="activer_fenetre",
    description="Met au premier plan une fenetre deja ouverte (par son titre ou son programme) et verifie "
                "qu'elle y est : « passe sur Spotify », « va sur la fenetre Chrome », « passe sur VS Code ».",
    parametres={"type": "object", "properties": {"titre": {"type": "string"}}, "required": ["titre"]},
    mcp_expose=False,
)
def activer_fenetre(titre: str) -> str:
    f = _activer(titre)
    if not f:
        return ResultatOutil(f"Je ne trouve pas de fenêtre « {titre} » ouverte.", succes=False, erreur="introuvable")
    r = _resultat_fenetre(f[1][:60], f, deja_ouverte=True)
    if not r.succes:
        return ResultatOutil(f"J'ai trouvé la fenêtre « {f[1][:60]} » mais je n'ai pas pu la mettre au premier plan.",
                             succes=False, verifie=True, details=r.details, erreur="focus")
    return ResultatOutil(f"Fenêtre « {f[1][:60]} » au premier plan.", succes=True,
                         verifie=r.verifie, details=r.details)


@outil(
    nom="appuyer_touches",
    description="Appuie sur une touche ou un raccourci clavier dans la fenetre active : « ctrl+l », "
                "« enter », « ctrl+shift+t », « alt+tab », « win+d », « f5 », « echap », « tab », "
                "« ctrl+s » (enregistrer).",
    parametres={"type": "object", "properties": {"combinaison": {"type": "string"}}, "required": ["combinaison"]},
    mcp_expose=False,
)
def appuyer_touches(combinaison: str) -> str:
    try:
        codes = analyser_combinaison(combinaison)
    except ValueError as e:
        return ResultatOutil(f"Je ne connais pas cette touche ({e}).", succes=False, erreur="touche")
    if frozenset(codes) in _INTERDITES:
        return ResultatOutil("Je n'appuie pas sur Ctrl+Alt+Suppr.", succes=False, erreur="interdit")
    try:
        _appuyer(codes)
    except Exception as e:
        return ResultatOutil(f"Je n'ai pas pu envoyer {combinaison} ({e}).", succes=False, erreur="saisie")
    return ResultatOutil(f"{combinaison} envoyé.", succes=True, verifie=False)


def _norm_texte(texte):
    t = unicodedata.normalize("NFC", str(texte or "")).replace("\xa0", " ")
    return " ".join(t.split())


def _texte_retrouve(attendu, lu):
    """Le texte tape est-il dans le contenu relu ? (espaces/retours a la ligne neutralises)."""
    a, l = _norm_texte(attendu), _norm_texte(lu)
    return bool(a) and a in l


_SCRIPT_RELIRE = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$w = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][int64]$env:JARVIS_HWND)
if ($null -eq $w) { throw 'fenetre introuvable' }
$prop = [System.Windows.Automation.AutomationElement]::ControlTypeProperty
$cond = New-Object System.Windows.Automation.OrCondition(
  (New-Object System.Windows.Automation.PropertyCondition($prop, [System.Windows.Automation.ControlType]::Edit)),
  (New-Object System.Windows.Automation.PropertyCondition($prop, [System.Windows.Automation.ControlType]::Document)))
$els = $w.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
$out = New-Object System.Collections.ArrayList
foreach ($e in $els) {
  try {
    $p = $null
    if ($e.TryGetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern, [ref]$p)) {
      [void]$out.Add($p.DocumentRange.GetText(20000))
    } elseif ($e.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern, [ref]$p)) {
      [void]$out.Add($p.Current.Value)
    }
  } catch { }
}
ConvertTo-Json -InputObject @{ texte = ($out -join "`n") } -Compress
"""


def _relire_wm_gettext(hwnd):
    """Lecture RAPIDE (quelques ms) du texte des zones d'edition par WM_GETTEXT, sans PowerShell.
    Renvoie le texte lu, ou None si aucune zone d'edition n'a repondu (le relai UIA prend alors le relais)."""
    if not EST_WINDOWS or not hwnd:
        return None
    try:
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)      # instance privee : n'altere pas user32 global
        envoyer = u.SendMessageTimeoutW
        envoyer.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, ctypes.c_void_p,
                            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        envoyer.restype = ctypes.c_size_t
        recus, nom_classe = [], ctypes.create_unicode_buffer(128)
        proc_t = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def lire(h):
            n = ctypes.c_size_t(0)
            if not envoyer(h, 0x000E, 0, None, 2, 1500, ctypes.byref(n)) or not (0 < n.value < 500000):
                return
            tampon = ctypes.create_unicode_buffer(int(n.value) + 1)
            r = ctypes.c_size_t(0)
            if envoyer(h, 0x000D, int(n.value) + 1, ctypes.cast(tampon, ctypes.c_void_p), 2, 1500, ctypes.byref(r)):
                recus.append(tampon.value)

        def rappel(h, _):
            u.GetClassNameW(h, nom_classe, 128)
            if "edit" in nom_classe.value.lower() or "scintilla" in nom_classe.value.lower():
                lire(h)
            return True

        rappel_c = proc_t(rappel)
        u.EnumChildWindows(hwnd, rappel_c, 0)
        return "\n".join(recus) if recus else None
    except Exception as exc:
        LOG.info("relecture WM_GETTEXT indisponible : %s", exc)
        return None


def _relire_texte(hwnd):
    """Texte actuellement affiche dans les zones d'edition de la fenetre, ou None.
    Essaie d'abord WM_GETTEXT (rapide), puis UI Automation via PowerShell (lent : jusqu'a 25 s)."""
    if not hwnd:
        return None
    rapide = _relire_wm_gettext(hwnd)
    if rapide:
        return rapide
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT_RELIRE],
                           capture_output=True, timeout=25,
                           env={**os.environ, "JARVIS_HWND": str(int(hwnd))},
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if r.returncode != 0:
            LOG.info("relecture UIA impossible : %s", r.stderr.decode("utf-8", "replace")[:300])
            return None
        donnees = json.loads(r.stdout.decode("utf-8-sig", "replace").strip() or "{}")
        return str(donnees.get("texte", ""))
    except Exception as exc:
        LOG.info("relecture UIA indisponible : %s", exc)
        return None


@outil(
    nom="taper_texte",
    description="TAPE du texte au clavier dans la fenetre/le champ actif d'une application Windows "
                "(Bloc-notes, Word, un champ de recherche...), accents et ponctuation compris. C'est le SEUL "
                "outil pour « ecris ... dans le Bloc-notes », « tape ... ». Ce n'est PAS noter (qui range une "
                "idee dans les notes internes de Jarvis). Indique fenetre (ex. « bloc-notes ») pour que le "
                "texte aille bien dans cette application : elle est activee et le focus verifie avant de "
                "taper, puis le texte est relu quand c'est possible. Jamais de mot de passe, de code "
                "bancaire ni de paiement. entree=true valide avec Entree.",
    parametres={"type": "object", "properties": {
        "texte": {"type": "string", "description": "Texte EXACT a taper, sans le reformuler."},
        "entree": {"type": "boolean"},
        "fenetre": {"type": "string", "description": "Application/fenetre cible (optionnel)."}},
        "required": ["texte"]},
    mcp_expose=False,
)
def taper_texte(texte: str, entree: bool = False, fenetre: str = "") -> str:
    texte = str(texte if texte is not None else "")
    if not texte.strip():
        return ResultatOutil("Je n'ai rien à taper.", succes=False, erreur="vide")
    cible = None
    if fenetre:
        cible = _activer(fenetre)
        if not cible:
            return ResultatOutil(f"Je ne trouve pas la fenêtre « {fenetre} » : je ne tape rien.",
                                 succes=False, erreur="introuvable")
        if _ETAT["focus"] is False:
            return ResultatOutil(f"Je n'ai pas pu mettre « {fenetre} » au premier plan : je ne tape rien.",
                                 succes=False, verifie=True, erreur="focus")
    else:
        try:
            cible = _fenetre_cible("")
        except Exception:
            cible = None
    if cible and str(cible[2]).lower() in _TERMINAUX and not reglage("controle_pc.autoriser_terminal", False):
        return ResultatOutil("La fenêtre active est un terminal : je ne tape pas de texte à cet endroit.",
                             succes=False, erreur="terminal")
    try:
        _ecrire(texte)
        if entree:
            _appuyer([0x0D])
    except OSError as exc:
        return ResultatOutil(f"Je n'ai pas pu taper le texte ({exc}).", succes=False, erreur="saisie")
    details = {"caracteres": len(texte), "fenetre": cible[1] if cible else "", "hwnd": int(cible[0]) if cible else 0}
    lu = None
    if cible and not entree:
        for _ in range(3):
            time.sleep(0.25 + 0.002 * len(texte))
            lu = _relire_texte(cible[0])
            if lu is None or _texte_retrouve(texte, lu):
                break
    if lu is None:
        return ResultatOutil("C'est tapé, mais je n'ai pas pu vérifier le résultat à l'écran.",
                             succes=True, verifie=False, details=details)
    if _texte_retrouve(texte, lu):
        return ResultatOutil("C'est tapé et je l'ai vérifié à l'écran.", succes=True, verifie=True, details=details)
    LOG.warning("taper_texte : texte attendu %r, relu %r", texte[:120], str(lu)[:200])
    return ResultatOutil("J'ai envoyé le texte, mais je ne le retrouve pas dans la fenêtre.",
                         succes=False, verifie=True, details=details, erreur="verification")


def _controles(hwnd):
    """
    Récupère les contrôles UI Automation d'une fenêtre Windows.

    Retour :
        [(type, nom, x, y), ...]

    Améliorations :
    - Gestion des erreurs PowerShell
    - Vérification du handle
    - Recherche limitée
    - Gestion des réponses JSON
    - Journalisation des anomalies
    """

    if not hwnd:
        LOG.warning("UI Automation : handle invalide.")
        return []

    script = r"""
$ErrorActionPreference = 'Stop'

try {
    # Sans cela, BoundingRectangle est « virtualise » (mis a l'echelle DPI) pour un processus
    # non DPI-aware : les clics par nom tombent a cote sur un ecran a 125 % / 150 %.
    Add-Type -Namespace Jarvis -Name Dpi -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
    [void][Jarvis.Dpi]::SetProcessDPIAware()

    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes

    $hwnd = [IntPtr][int64]$env:JARVIS_HWND

    $window = [System.Windows.Automation.AutomationElement]::FromHandle($hwnd)

    if ($null -eq $window) {
        throw "Fenêtre UI Automation introuvable."
    }

    $condition = [System.Windows.Automation.Condition]::TrueCondition

    # Explorer progressivement l'arborescence UI Automation.
    # Profondeur maximale : 5 niveaux.
    # Nombre maximal d'éléments examinés : 200.

    $elements = New-Object System.Collections.ArrayList
    $file = New-Object System.Collections.Queue

    $file.Enqueue(@($window, 0))

    while ($file.Count -gt 0 -and $elements.Count -lt 200) {

        $item = $file.Dequeue()
        $parent = $item[0]
        $profondeur = [int]$item[1]

        if ($profondeur -ge 5) {
            continue
        }

        try {
            $enfants = $parent.FindAll(
                [System.Windows.Automation.TreeScope]::Children,
                $condition
            )

            foreach ($enfant in $enfants) {

                [void]$elements.Add($enfant)

                if ($elements.Count -ge 200) {
                    break
                }

                $file.Enqueue(@($enfant, ($profondeur + 1)))
            }

        } catch {
            continue
        }
    }

    $resultats = @()

    foreach ($element in $elements) {

        try {
            $nom = $element.Current.Name
            $type = $element.Current.LocalizedControlType
            $rectangle = $element.Current.BoundingRectangle

            if (
                -not [string]::IsNullOrWhiteSpace($nom) -and
                $rectangle.Width -gt 0 -and
                $rectangle.Height -gt 0
            ) {

                $resultats += [PSCustomObject]@{
                    t = $type
                    n = $nom
                    x = [int]($rectangle.X + $rectangle.Width / 2)
                    y = [int]($rectangle.Y + $rectangle.Height / 2)
                }
            }

        } catch {
            continue
        }
    }

    ConvertTo-Json -InputObject @($resultats) -Compress -Depth 4

} catch {
    Write-Error $_
    exit 1
}
"""

    try:
        resultat = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script
            ],
            capture_output=True,
            timeout=15,
            env={
                **os.environ,
                "JARVIS_HWND": str(hwnd)
            },
            creationflags=getattr(
                subprocess,
                "CREATE_NO_WINDOW",
                0
            )
        )

        if resultat.returncode != 0:
            erreur = resultat.stderr.decode(
                "utf-8",
                errors="replace"
            )

            LOG.error(
                "UI Automation PowerShell : %s",
                erreur[:1000]
            )

            return []

        sortie = resultat.stdout.decode(
            "utf-8-sig",
            errors="replace"
        ).strip()

        if not sortie:
            return []

        donnees = json.loads(sortie)

        if isinstance(donnees, dict):
            donnees = [donnees]

        if not isinstance(donnees, list):
            return []

        controles = []

        for element in donnees:

            if not isinstance(element, dict):
                continue

            nom = str(element.get("n") or "").strip()

            if not nom:
                continue

            controles.append((
                str(element.get("t") or ""),
                nom,
                int(element.get("x") or 0),
                int(element.get("y") or 0)
            ))

        return controles

    except subprocess.TimeoutExpired:
        LOG.warning(
            "UI Automation : délai dépassé pour HWND=%s",
            hwnd
        )
        return []

    except (ValueError, TypeError, KeyError) as erreur:
        LOG.exception(
            "UI Automation : réponse invalide : %s",
            erreur
        )
        return []

    except Exception:
        LOG.exception(
            "Erreur inattendue dans _controles()"
        )
        return []

def choisir_controle(controles, nom):
    q = _sa(nom).strip()
    exact = [c for c in controles if _sa(c[1]).strip() == q]
    debut = [c for c in controles if _sa(c[1]).startswith(q)]
    partiel = [c for c in controles if q in _sa(c[1])]
    for groupe in (exact, debut, sorted(partiel, key=lambda c: len(c[1]))):
        if groupe:
            return groupe[0]
    return None

def _infos_fenetre(hwnd):
    """
    Récupère les informations d'une fenêtre Windows
    directement à partir de son handle.

    Retourne :
        (hwnd, titre, executable)

    Ou None si le handle est invalide.
    """

    if not hwnd:
        return None

    if not user32.IsWindow(hwnd):
        return None

    # --------------------------------------------------
    # 1. Récupérer le titre
    # --------------------------------------------------

    longueur = user32.GetWindowTextLengthW(hwnd)

    buffer = ctypes.create_unicode_buffer(longueur + 1)

    user32.GetWindowTextW(
        hwnd,
        buffer,
        longueur + 1
    )

    titre = buffer.value

    # --------------------------------------------------
    # 2. Récupérer l'identifiant du processus
    # --------------------------------------------------

    pid = wintypes.DWORD()

    user32.GetWindowThreadProcessId(
        hwnd,
        ctypes.byref(pid)
    )

    executable = ""

    if pid.value:

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

        processus = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value
        )

        if processus:

            try:

                chemin = ctypes.create_unicode_buffer(520)

                taille = wintypes.DWORD(520)

                succes = kernel32.QueryFullProcessImageNameW(
                    processus,
                    0,
                    chemin,
                    ctypes.byref(taille)
                )

                if succes:
                    executable = os.path.basename(
                        chemin.value
                    ).lower()

            finally:

                kernel32.CloseHandle(processus)

    return (
        int(hwnd),
        titre,
        executable
    )

def _fenetre_cible(fenetre):
    """
    Identifie la fenêtre sur laquelle Jarvis doit agir.

    Si un nom est fourni :
        recherche et active cette fenêtre.

    Sinon :
        utilise directement la fenêtre active Windows.
    """

    # Cas 1 : une fenêtre spécifique est demandée
    if fenetre:

        resultat = _activer(fenetre)

        if resultat:
            return resultat

        LOG.warning(
            "Fenêtre demandée introuvable : %s",
            fenetre
        )

        return None

    # Cas 2 : utiliser la fenêtre actuellement active
    hwnd = user32.GetForegroundWindow()

    if not hwnd:

        LOG.warning(
            "Windows ne retourne aucune fenêtre active."
        )

        return None

    # Récupérer directement ses informations
    resultat = _infos_fenetre(hwnd)

    if resultat:

        LOG.debug(
            "Fenêtre active : %s | %s | HWND=%s",
            resultat[1],
            resultat[2],
            resultat[0]
        )

        return resultat

    LOG.warning(
        "Impossible d'identifier la fenêtre active."
    )

    return None


@outil(
    nom="cliquer_bouton",
    description="Clique sur un bouton, un lien, un onglet ou un element de menu PAR SON NOM dans la "
                "fenetre active (ou la fenetre indiquee), sans capture d'ecran : « clique sur Enregistrer », "
                "« clique sur Paramètres ». Si le nom est introuvable, utilise lister_controles.",
    parametres={"type": "object", "properties": {"nom": {"type": "string"}, "fenetre": {"type": "string"},
                                                  "double": {"type": "boolean"}}, "required": ["nom"]},
    mcp_expose=False,
)
def cliquer_bouton(nom: str, fenetre: str = "", double: bool = False) -> str:
    f = _fenetre_cible(fenetre)
    if not f:
        return "Je ne trouve pas cette fenêtre."
    try:
        c = choisir_controle(_controles(f[0]), nom)
    except Exception:
        LOG.exception("cliquer_bouton")
        return "Je n'arrive pas à lire les boutons de cette fenêtre."
    if not c:
        if _est_sensible(nom):
            return _MSG_SENSIBLE
        vu = _clic_vision(nom, double=double)       # repli : on cherche a l'ecran avec le modele de vision
        return vu or f"Je ne vois pas de bouton « {nom} » dans {f[1][:40]}."
    if _est_sensible(nom):
        return _MSG_SENSIBLE
    from tools.souris import _BOUTONS, _placer_curseur, _user32
    details = {"controle": c[1][:50], "x": c[2], "y": c[3], "fenetre": f[1][:60]}
    if not _placer_curseur(c[2], c[3]):
        return ResultatOutil(f"Je n'ai pas pu déplacer la souris sur « {c[1][:50]} ».",
                             succes=False, details=details, erreur="curseur")
    try:
        px, py = _position()
    except Exception:
        px = py = None
    if px is not None and (abs(px - c[2]) > 3 or abs(py - c[3]) > 3):
        # Preuve avant le clic : le curseur n'est pas la ou on l'a demande (DPI, ecran, fenetre admin).
        return ResultatOutil(f"Le curseur n'est pas arrivé sur « {c[1][:50]} » : je ne clique pas.",
                             succes=False, verifie=True, details={**details, "curseur": [px, py]},
                             erreur="curseur")
    down, up = _BOUTONS["gauche"]
    for _ in range(2 if double else 1):
        _user32.mouse_event(down, 0, 0, 0, 0)
        _user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.08)
    # Le clic est envoye et la position du curseur constatee ; l'EFFET du clic n'est pas verifie.
    return ResultatOutil(f"J'ai cliqué sur {c[1][:50]}.", succes=True, verifie=False,
                         details={**details, "curseur_verifie": px is not None})


@outil(
    nom="lister_controles",
    description="Liste les boutons/liens/onglets visibles de la fenetre active (ou indiquee), pour savoir "
                "sur quoi cliquer avec cliquer_bouton.",
    parametres={"type": "object", "properties": {"fenetre": {"type": "string"}}},
    mcp_expose=False,
)
def lister_controles(fenetre: str = "") -> str:
    f = _fenetre_cible(fenetre)
    if not f:
        return "Je ne trouve pas cette fenêtre."
    try:
        noms = []
        for t, n, _, _ in _controles(f[0]):
            if n not in noms:
                noms.append(n[:40])
    except Exception:
        LOG.exception("lister_controles")
        return "Je n'arrive pas à lire cette fenêtre."
    return "Éléments : " + ", ".join(noms[:40]) if noms else "Je ne vois aucun élément cliquable."


@outil(
    nom="rechercher_dans_application",
    description="Fait une RECHERCHE dans une application de bureau : ouvre l'appli si besoin, met sa "
                "fenetre au premier plan, active sa barre de recherche et tape la requete. Pour « cherche "
                "Daft Punk sur Spotify », « cherche Marie dans WhatsApp ». Pour un site web, utilise browser_open.",
    parametres={"type": "object", "properties": {"application": {"type": "string"}, "requete": {"type": "string"}},
                "required": ["application", "requete"]},
    mcp_expose=False,
    lent=True,
    phrase_attente="Je lance la recherche.",
)
def rechercher_dans_application(application: str, requete: str) -> str:
    if not _activer(application):
        if not _lancer(application):
            from tools.navigateur import _RECHERCHES, browser_open
            site = _sa(application).strip()
            if site in _RECHERCHES:                       # appli absente : on cherche sur le site web
                return browser_open(url=site, recherche=str(requete))
            return f"Je ne trouve pas l'application « {application} »."
        if not _attendre_fenetre(application, 15.0):
            return ResultatOutil(f"{application} ne s'ouvre pas.", succes=False, erreur="fenetre_absente")
        time.sleep(1.5)                                     # laisse l'interface se construire
    elif _ETAT["focus"] is False:
        return ResultatOutil(f"Je n'arrive pas à mettre {application} au premier plan : je ne lance pas la recherche.",
                             succes=False, verifie=True, erreur="focus")
    raccourcis = {**_RACCOURCIS_RECHERCHE, **(reglage("controle_pc.recherche_raccourcis", {}) or {})}
    combo = next((v for k, v in raccourcis.items() if k in _sa(application)), "ctrl+f")
    try:
        _appuyer(analyser_combinaison(combo))
        time.sleep(0.35)
        _appuyer(analyser_combinaison("ctrl+a"))
        _ecrire(str(requete))
        time.sleep(0.2)
        _appuyer([0x0D])
    except OSError as exc:
        return ResultatOutil(f"Je n'ai pas pu saisir la recherche ({exc}).", succes=False, erreur="saisie")
    return ResultatOutil(f"J'ai lancé la recherche « {requete} » dans {application}.", succes=True, verifie=False)


# ============================================================ vision, souris, navigateur
_SENSIBLES = ("supprimer", "effacer", "payer", "paiement", "acheter", "commander", "valider la commande",
              "envoyer", "virement", "formater", "desinstaller", "mot de passe", "confirmer l achat")
_MSG_SENSIBLE = ("Je ne clique pas là-dessus sans ta confirmation. Dis « prends le contrôle de mon PC "
                 "et clique dessus » pour que je te demande confirmation.")
_SCHEMA_LOC = {"type": "object", "properties": {
    "trouve": {"type": "boolean"}, "x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["trouve"]}


def _est_sensible(nom):
    n = _sa(nom).replace("'", " ")
    return any(m in n for m in _SENSIBLES)


def _clic_vision(nom, bouton="gauche", double=False):
    """Clique « a l'oeil » : capture, le modele de vision localise l'element, on clique.
    Renvoie le message, ou None si la vision est indisponible."""
    try:
        from core import cloud
        from tools import ecran, souris
        cap = ecran.capture_screen(0)
        if not isinstance(cap, dict):
            return None
        geo = ecran.derniere_capture() or {}
        texte = (f"Capture d'ecran de {geo.get('largeur')}x{geo.get('hauteur')} pixels. Localise le centre de "
                 f"l'element a cliquer : « {nom} ». Reponds avec les coordonnees en pixels de CETTE image "
                 f"(x vers la droite, y vers le bas) ; trouve=false si tu ne le vois pas clairement.")
        rep = cloud.decider_action_vision(
            "Tu localises un element d'interface sur une capture d'ecran. Tu ne devines jamais.",
            texte, cap["image"]["data"], _SCHEMA_LOC, nom_outil="localiser",
            description="Position de l'element demande.", qualite=True)
        if not rep.get("trouve") or rep.get("x") is None or rep.get("y") is None:
            return f"Je ne vois pas « {nom} » à l'écran."
        souris.cliquer_ecran(int(rep["x"]), int(rep["y"]), bouton, double)
        return f"J'ai cliqué sur {nom}."
    except Exception:
        LOG.exception("clic par vision")
        return None


def _position():
    import ctypes.wintypes as wt
    pt = wt.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


@outil(
    nom="souris_clic",
    description="Clique avec la souris la ou se trouve le curseur (gauche, droit, double). Pour « clique », "
                "« clique ici », « double clic », « clic droit ».",
    parametres={"type": "object", "properties": {"bouton": {"type": "string", "enum": ["gauche", "droite", "milieu"]},
                                                  "double": {"type": "boolean"}}},
    mcp_expose=False,
)
def souris_clic(bouton: str = "gauche", double: bool = False) -> str:
    from tools.souris import _BOUTONS, _user32
    b = _BOUTONS.get((bouton or "gauche").lower())
    if not b:
        return "Bouton inconnu (gauche, droite ou milieu)."
    for _ in range(2 if double else 1):
        _user32.mouse_event(b[0], 0, 0, 0, 0)
        _user32.mouse_event(b[1], 0, 0, 0, 0)
        time.sleep(0.07)
    return "Double clic." if double else ("Clic droit." if bouton.startswith("d") else "Clic.")


@outil(
    nom="souris_defiler",
    description="Fait defiler la page/fenetre avec la molette : sens haut ou bas, nombre de crans (5 par defaut).",
    parametres={"type": "object", "properties": {"sens": {"type": "string", "enum": ["haut", "bas"]},
                                                  "crans": {"type": "integer"}}, "required": ["sens"]},
    mcp_expose=False,
)
def souris_defiler(sens: str, crans: int = 5) -> str:
    from tools.souris import _user32
    n = max(1, min(30, int(crans or 5)))
    delta = (120 if str(sens).lower().startswith("h") else -120)
    for _ in range(n):
        _user32.mouse_event(0x0800, 0, 0, delta & 0xFFFFFFFF, 0)
        time.sleep(0.02)
    return "Je fais défiler vers le haut." if delta > 0 else "Je fais défiler vers le bas."


@outil(
    nom="souris_deplacer",
    description="Deplace le curseur de la souris : direction haut/bas/gauche/droite (de N pixels) ou centre.",
    parametres={"type": "object", "properties": {"direction": {"type": "string",
                                                                "enum": ["haut", "bas", "gauche", "droite", "centre"]},
                                                  "pixels": {"type": "integer"}}, "required": ["direction"]},
    mcp_expose=False,
)
def souris_deplacer(direction: str, pixels: int = 200) -> str:
    from tools.souris import _placer_curseur
    d = _sa(direction)
    px = max(1, min(3000, int(pixels or 200)))
    if d == "centre":
        u = ctypes.windll.user32
        x, y = u.GetSystemMetrics(0) // 2, u.GetSystemMetrics(1) // 2
    else:
        x, y = _position()
        dx, dy = {"haut": (0, -px), "bas": (0, px), "gauche": (-px, 0), "droite": (px, 0)}.get(d, (0, 0))
        x, y = x + dx, y + dy
    return "J'ai déplacé la souris." if _placer_curseur(max(0, x), max(0, y)) else "Je n'ai pas pu déplacer la souris."


_NAVIGATEURS = {"navigateur": "", "un navigateur": "", "mon navigateur": "", "le navigateur": "", "internet": "",
                "chrome": "chrome", "google chrome": "chrome", "firefox": "firefox", "mozilla firefox": "firefox",
                "edge": "edge", "microsoft edge": "edge", "brave": "brave", "opera": "opera"}
_NOMS_MENU = {"chrome": "Google Chrome", "firefox": "Firefox", "edge": "Microsoft Edge", "brave": "Brave",
              "opera": "Opera"}


@outil(
    nom="ouvrir_navigateur",
    description="Ouvre le navigateur web (« ouvre mon navigateur », « ouvre Chrome », « lance Firefox », « Edge ») "
                "sans page precise. Pour un SITE ou une recherche, utilise browser_open.",
    parametres={"type": "object", "properties": {"nom": {"type": "string"}}},
    mcp_expose=False,
)
def ouvrir_navigateur(nom: str = "") -> str:
    cle = _NAVIGATEURS.get(_sa(nom).strip().replace("'", " "), _sa(nom).strip())
    from core import ouvrir_web
    if not cle:                                           # « mon navigateur » : celui configure, sinon le defaut
        pref = ouvrir_web.navigateur_prefere()
        cle = pref if pref in _NOMS_MENU and pref != "firefox" else ""
        if not cle:
            if ouvrir_web.ouvrir_url("https://www.google.com"):
                return f"{ouvrir_web.nom_navigateur().capitalize()} est ouvert."
            return "Je n'ai pas réussi à ouvrir le navigateur."
    nom_menu = _NOMS_MENU.get(cle, cle)
    if _activer(cle) or _activer(nom_menu):
        return f"{nom_menu} est au premier plan."
    if cle == "chrome":
        try:
            from tools.navigateur import _chrome_exe
            exe = _chrome_exe()
            if exe:
                subprocess.Popen([exe])
                return "Chrome est ouvert."
        except Exception:
            LOG.exception("ouvrir_navigateur chrome")
    if _lancer(nom_menu) or _lancer(cle):
        return f"{nom_menu} est ouvert."
    if ouvrir_web.ouvrir_url("https://www.google.com"):
        return "J'ai ouvert ton navigateur par défaut."
    return f"Je ne trouve pas {nom_menu} sur ce PC."


# ============================================================ routeur deterministe (sans LLM)
_VERBES = ("ouvre|ouvrir|lance|lancer|demarre|démarre|clique|cliquer|appuie|appuyer|tape|taper|ecris|écris|"
           "saisis|cherche|chercher|recherche|rechercher|passe|bascule|ferme|fermer|mets|met|monte|remonte|"
           "baisse|descends|defile|défile|deplace|déplace|active|desactive|désactive|va|vas|joue|arrete|arrête|"
           "augmente|diminue|reduis|réduis|agrandis|minimise|maximise|connecte|selectionne|sélectionne|"
           "actualise|rafraichis|rafraîchis|copie|colle|enregistre|verrouille|montre|affiche|coupe")
_CONNECTEURS = re.compile(rf"\s*(?:,|;|\bet puis\b|\bpuis\b|\bensuite\b|\bet\b)\s+(?=(?:{_VERBES})\b)", re.I)
_RACCOURCIS_PHRASES = {
    "ferme la fenetre": "alt+f4", "ferme cette fenetre": "alt+f4", "ferme la fenetre active": "alt+f4",
    "ferme l onglet": "ctrl+w", "ferme cet onglet": "ctrl+w", "nouvel onglet": "ctrl+t",
    "ouvre un nouvel onglet": "ctrl+t", "onglet suivant": "ctrl+tab", "onglet precedent": "ctrl+shift+tab",
    "rouvre l onglet": "ctrl+shift+t", "actualise": "f5", "actualise la page": "f5", "rafraichis": "f5",
    "rafraichis la page": "f5", "recharge la page": "f5", "page precedente": "alt+left",
    "retour arriere": "alt+left", "reviens en arriere": "alt+left", "page suivante": "alt+right",
    "minimise": "win+down", "minimise la fenetre": "win+down", "reduis la fenetre": "win+down",
    "maximise": "win+up", "maximise la fenetre": "win+up", "agrandis la fenetre": "win+up",
    "plein ecran": "f11", "montre le bureau": "win+d", "affiche le bureau": "win+d",
    "copie": "ctrl+c", "copie ca": "ctrl+c", "copie la selection": "ctrl+c", "colle": "ctrl+v", "colle ca": "ctrl+v",
    "selectionne tout": "ctrl+a", "enregistre": "ctrl+s", "sauvegarde": "ctrl+s", "enregistre le fichier": "ctrl+s",
    "annule la derniere action": "ctrl+z", "defais": "ctrl+z", "refais": "ctrl+y",
    "fais une capture d ecran": "win+shift+s", "prends une capture d ecran": "win+shift+s",
    "verrouille l ordinateur": "win+l", "verrouille le pc": "win+l", "verrouille la session": "win+l",
    "enregistre le": "ctrl+s", "enregistre la": "ctrl+s", "sauvegarde le": "ctrl+s",
    "sauvegarde la": "ctrl+s", "enregistre ca": "ctrl+s", "enregistre le document": "ctrl+s",
    "tout en haut": "ctrl+home", "en haut de la page": "ctrl+home", "tout en bas": "ctrl+end",
    "en bas de la page": "ctrl+end",
}
_SITES_RECHERCHE_WEB = {"google", "internet", "le web", "web", "le net", "net", "google chrome"}
_DEICTIQUES = {"ca", "ce", "cela", "ici", "la", "celui ci", "celui la", "ce bouton", "ce lien", "dessus"}
_SANS_TEXTE = ("un ", "une ", "moi", "mon ", "ma ", "a ", "au ", "sur ", "dans ", "pour ", "le ", "la ", "les ")


_VERBES_DICTEE = r"(?:tape|taper|[ée]cris|[ée]crire|saisis|saisir)"
_POLITESSE_FIN = re.compile(r"[\s,]+(?:s['’ ]il (?:te|vous) pla[iî]t|stp|merci)\s*[.!?]*\s*$", re.I)


def _texte_dicte(phrase):
    """Texte a taper, extrait de la phrase BRUTE : ponctuation, accents et casse conserves.

    (Avant, le texte etait reconstruit a partir de mots nus : « Bonjour, je suis Jarvis. »
    devenait « Bonjour je suis Jarvis » — virgules et point perdus.)
    """
    m = re.search(rf"\b{_VERBES_DICTEE}\b\s*[:\-–—]?\s*(.*)$", str(phrase or ""), re.I | re.S)
    if not m:
        return ""
    texte = _POLITESSE_FIN.sub("", m.group(1)).strip()
    if len(texte) >= 2 and (texte[0], texte[-1]) in {("«", "»"), ('"', '"'), ("“", "”"), ("'", "'")}:
        texte = texte[1:-1].strip()
    return texte.lstrip(":").strip()


def _tokens(phrase):
    orig = re.findall(r"[0-9A-Za-zÀ-ÖØ-öø-ÿŒœ]+", str(phrase or ""))
    return orig, [_sa(t) for t in orig]


def _nettoyer_politesse(norm, orig):
    from tools.apps import _PREFIXES_POLITES, _SUFFIXES_POLITES
    changed = True
    while changed and norm:
        changed = False
        for pre in _PREFIXES_POLITES:
            if tuple(norm[:len(pre)]) == pre and len(norm) > len(pre):
                del norm[:len(pre)], orig[:len(pre)]
                changed = True
                break
        for suf in _SUFFIXES_POLITES:
            if tuple(norm[-len(suf):]) == suf and len(norm) > len(suf):
                del norm[-len(suf):], orig[-len(suf):]
                changed = True
                break
    return norm, orig


def _tranche(p, orig, debut, fin):
    """Mots d'origine (accents, casse) correspondant a p[debut:fin]."""
    return orig[p[:debut].count(" "): p[:fin].count(" ") + 1]


def _est_combinaison(texte):
    try:
        analyser_combinaison(texte)
        return True
    except ValueError:
        return False


def _route_simple(phrase):
    """(outil, arguments) pour UNE commande PC claire, sinon None."""
    orig, norm = _tokens(phrase)
    norm, orig = _nettoyer_politesse(list(norm), list(orig))
    if not norm:
        return None
    p = " ".join(norm)

    if p in _RACCOURCIS_PHRASES:
        return "appuyer_touches", {"combinaison": _RACCOURCIS_PHRASES[p]}
    if re.fullmatch(r"(?:fais un |fais )?double clic(?: gauche)?|double clique(?: gauche)?|clique deux fois|clic double", p):
        return "souris_clic", {"bouton": "gauche", "double": True}
    if re.fullmatch(r"(?:fais un )?(?:clic|clique|cliquer) droit|clique avec le bouton droit|clic avec le bouton droit", p):
        return "souris_clic", {"bouton": "droite"}
    if re.fullmatch(r"(?:fais un )?(?:clic|clique|cliquer)(?: (?:ici|dessus|la|gauche|sur ca|sur cela))?", p):
        return "souris_clic", {"bouton": "gauche"}

    m = re.fullmatch(r"(descends|defile|fais defiler|scroll|scrolle|monte|remonte)"
                     r"(?: la page| l ecran| vers le (haut|bas)| en (haut|bas)| (un peu|beaucoup))*(?: de (\d+))?", p)
    if m:
        haut = m.group(1) in ("monte", "remonte") or "haut" in p
        crans = int(m.group(5)) if m.group(5) else (10 if "beaucoup" in p else 2 if "un peu" in p else 5)
        return "souris_defiler", {"sens": "haut" if haut else "bas", "crans": crans}

    m = re.fullmatch(r"(?:deplace|deplacer|bouge|bouger)(?: la souris| le curseur| le pointeur)?"
                     r"(?: (?:vers|a|sur))?(?: la | le )?\s*(haut|bas|gauche|droite)(?: de (\d+))?(?: pixels)?", p)
    if m:
        return "souris_deplacer", {"direction": m.group(1), "pixels": int(m.group(2) or 200)}
    if re.fullmatch(r"centre la souris|mets la souris au centre|souris au centre", p):
        return "souris_deplacer", {"direction": "centre"}

    m = re.fullmatch(r"(?:appuie|appuyer|presse|presser|touche) (?:sur )?(?:la touche |les touches )?(.+)", p)
    if m and _est_combinaison(m.group(1).replace(" plus ", " ")):
        return "appuyer_touches", {"combinaison": m.group(1).replace(" plus ", "+").replace(" ", "+")}

    m = re.fullmatch(r"(?:clique|cliquer|clic|appuie|appuyer|presse|selectionne|selectionner|choisis) (?:sur |dessus )"
                     r"(?:le |la |les |l |un |une |mon |ma )?(?:bouton |lien |onglet |icone |menu |option |case )?(.+)", p)
    if m:
        cible = m.group(1).strip()
        if cible in _DEICTIQUES:
            return "souris_clic", {"bouton": "gauche"}
        return "cliquer_bouton", {"nom": " ".join(_tranche(p, orig, m.start(1), m.end(1)))}

    m = re.match(r"(?:tape|taper|ecris|ecrire|saisis|saisir)\b\s*(.*)", p)
    if m and m.group(1).strip() and not m.group(1).startswith(_SANS_TEXTE):
        texte = _texte_dicte(phrase) or " ".join(_tranche(p, orig, m.start(1), len(p)))
        return "taper_texte", {"texte": texte}

    m = re.fullmatch(r"(?:passe|bascule) (?:sur|a|vers) (?:la fenetre |l application |l appli |la |le |l )?(.+)", p)
    if m:
        return "activer_fenetre", {"titre": " ".join(_tranche(p, orig, m.start(1), m.end(1)))}

    m = re.fullmatch(r"(?:cherche|chercher|recherche|rechercher|trouve|trouver)(?: moi)? (.+?) "
                     r"(?:sur|dans|avec|via) (?:l application |l appli |le site |l |la |le )?(.+)", p)
    if m:
        requete = " ".join(_tranche(p, orig, m.start(1), m.end(1)))
        cible = m.group(2).strip()
        from tools.navigateur import _RECHERCHES
        if cible in _SITES_RECHERCHE_WEB:
            return "browser_open", {"recherche": requete}
        if cible in _RECHERCHES and cible != "spotify":
            return "browser_open", {"url": cible, "recherche": requete}
        return "rechercher_dans_application", {"application": cible, "requete": requete}
    return None


_APPEL = re.compile(r"^\s*(?:(?:hey|ok|dis|salut)\s+)?jarvis\s*[,:;.!]*\s*", re.I)


def _retirer_appel(phrase):
    """Retire le nom d'appel en tete (« Jarvis, ... ») : sans cela la virgule qui le suit etait prise pour
    un connecteur et « Jarvis » devenait une etape a part, ce qui faisait echouer toute la chaine."""
    phrase = str(phrase or "")
    return _APPEL.sub("", phrase, count=1) or phrase


_DEBUT_DICTEE = re.compile(rf"\s*(?:jarvis\s*[,:]?\s*)?{_VERBES_DICTEE}\b", re.I)
_VERBES_SUITE_DICTEE = re.compile(r"(?:enregistre|sauvegarde)\b", re.I)


def _decouper(phrase):
    """Coupe une phrase en commandes, SEULEMENT devant un verbe d'action.

    Apres un verbe de dictee (« ecris ... »), le reste est du TEXTE : on ne coupe plus que sur
    « puis » / « ensuite » ou devant « enregistre / sauvegarde » (« ecris bonjour et enregistre »).
    """
    phrase = _retirer_appel(phrase)
    segments, debut = [], 0
    for m in _CONNECTEURS.finditer(phrase):
        courant = phrase[debut:m.start()]
        if _DEBUT_DICTEE.match(courant):
            lien = m.group(0).lower()
            suite = phrase[m.end():]
            if not ("puis" in lien or "ensuite" in lien or _VERBES_SUITE_DICTEE.match(suite)):
                continue
        segments.append(courant)
        debut = m.end()
    segments.append(phrase[debut:])
    nets = []
    for i, seg in enumerate(segments):
        dictee = bool(_DEBUT_DICTEE.match(seg))
        nets.append(seg.strip().rstrip(" ,;") if dictee else seg.strip(" .!?,;"))
    return [seg for seg in nets if seg]


def router_commande_pc(phrase, piece=""):
    """Route prioritaire (avant le LLM) : commande PC claire -> (outil, arguments). Plusieurs actions
    enchainees -> enchainer_commandes, SEULEMENT si chacune est comprise ; sinon None (le LLM prend la main)."""
    try:
        segments = _decouper(phrase)
        if len(segments) < 2:
            return _route_simple(phrase)
        if len(segments) > 6:
            return None
        from core.routage_intentions import decider_prioritaire
        for s in segments:
            d = decider_prioritaire(s, piece)
            if d is None or d.type != "outil":
                return None
        return "enchainer_commandes", {"etapes": segments}
    except Exception:
        LOG.exception("router_commande_pc")
        return None


_OUVERTURES = {"ouvrir_application", "launch_app", "lancer_application_pc", "activer_fenetre",
               "ouvrir_navigateur"}


def _fenetre_de_l_etape(nom_outil, arguments):
    """Application/fenetre visee par une etape d'ouverture ou d'activation, sinon ''."""
    if nom_outil not in _OUVERTURES:
        return ""
    return str(arguments.get("nom") or arguments.get("titre") or "").strip()


@outil(
    nom="enchainer_commandes",
    description="Execute plusieurs commandes simples a la suite (« ouvre le Bloc-notes puis ecris Bonjour », "
                "« ouvre Chrome puis lance YouTube »). Chaque etape est une phrase de commande ; le texte a "
                "taper va dans l'application ouverte a l'etape precedente ; s'arrete a la premiere etape "
                "qui echoue et le dit.",
    parametres={"type": "object", "properties": {"etapes": {"type": "array", "items": {"type": "string"}}},
                "required": ["etapes"]},
    mcp_expose=False,
    lent=True,
    phrase_attente="J'enchaîne les actions.",
)
def enchainer_commandes(etapes: list) -> str:
    from core import registre
    from core.erreurs import message_humain
    from core.routage_intentions import decider_prioritaire
    dits, tout_reussi, tout_verifie, cible = [], True, True, ""
    for s in list(etapes or [])[:6]:
        d = decider_prioritaire(str(s))
        outil_obj = registre.get(d.outil) if d is not None and d.type == "outil" else None
        if outil_obj is None:
            dits.append(f"Je n'ai pas compris « {s} ».")
            tout_reussi = False
            break
        if getattr(outil_obj, "confirmation", False):
            dits.append(f"« {s} » demande une confirmation : dis-le-moi séparément.")
            tout_reussi = False
            break
        arguments = dict(d.arguments or {})
        # Le texte tape / le bouton clique visent l'application ouverte juste avant.
        if cible and d.outil in {"taper_texte", "cliquer_bouton"} and not arguments.get("fenetre"):
            arguments["fenetre"] = cible
        try:
            res = registre.executer(outil_obj, arguments)
        except Exception as exc:
            LOG.exception("enchainer_commandes : %s", s)
            dits.append(message_humain(exc, d.outil))
            tout_reussi = False
            break
        texte = str(res or "").strip()
        if texte:
            dits.append(texte)
        if isinstance(res, ResultatOutil):
            tout_verifie = tout_verifie and res.verifie
        else:
            tout_verifie = False
        if est_echec(res):
            tout_reussi = False
            LOG.warning("enchainer_commandes : etape en echec, arret : %s", s)
            break
        cible = _fenetre_de_l_etape(d.outil, arguments) or cible
        time.sleep(float(reglage("controle_pc.pause_etapes", 1.2) or 0))
    return ResultatOutil(" ".join(dits) or "Rien à faire.", succes=tout_reussi and bool(dits),
                         verifie=tout_reussi and tout_verifie and bool(dits),
                         erreur="" if tout_reussi else "etape_en_echec")
