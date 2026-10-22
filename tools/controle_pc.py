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
import subprocess
import time
import unicodedata

from core.config import reglage
from core.registre import outil
from ctypes import wintypes

# ============================================================
# CONFIGURATION DES API WINDOWS
# ============================================================

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Récupération de la fenêtre active
user32.GetForegroundWindow.restype = wintypes.HWND

# Vérification de l'existence d'une fenêtre
user32.IsWindow.argtypes = [wintypes.HWND]
user32.IsWindow.restype = wintypes.BOOL

# Vérification de la visibilité
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL

# Récupération du titre
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextLengthW.restype = ctypes.c_int

user32.GetWindowTextW.argtypes = [
    wintypes.HWND,
    wintypes.LPWSTR,
    ctypes.c_int
]
user32.GetWindowTextW.restype = ctypes.c_int

# Récupération du processus associé
user32.GetWindowThreadProcessId.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(wintypes.DWORD)
]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

# Gestion des processus
kernel32.OpenProcess.argtypes = [
    wintypes.DWORD,
    wintypes.BOOL,
    wintypes.DWORD
]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)
]
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
_APPS = {"liste": None}


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


def _ecrire(texte):
    """Saisie Unicode (accents compris) via SendInput, caractere par caractere."""
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
        ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(IN))

    for ch in texte:
        if ch == "\n":
            _appuyer([0x0D])
        else:
            envoyer(0, ord(ch), 0x0004)
            envoyer(0, ord(ch), 0x0004 | 0x0002)
        time.sleep(0.004)


def _fenetres():
    """[(hwnd, titre, exe)] des fenetres visibles avec un titre."""
    u, k = ctypes.windll.user32, ctypes.windll.kernel32
    res = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        n = u.GetWindowTextLengthW(hwnd)
        if n <= 0:
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


def _activer(requete):
    """
    Recherche une fenêtre Windows en privilégiant son exécutable.

    Priorités :
    1. Exécutable correspondant exactement
    2. Alias connu d'une application
    3. Titre correspondant exactement
    4. Titre contenant la recherche

    Les fenêtres de terminal sont exclues des recherches
    approximatives, sauf si elles sont explicitement demandées.
    """

    import unicodedata

    def normaliser(texte):
        texte = unicodedata.normalize("NFKD", str(texte))
        texte = "".join(
            c for c in texte
            if not unicodedata.combining(c)
        )
        return texte.replace("\xa0", " ").casefold().strip()

    requete_norm = normaliser(requete)

    if not requete_norm:
        return None

    alias = {
        "bloc-notes": "notepad.exe",
        "bloc notes": "notepad.exe",
        "notepad": "notepad.exe",
        "chrome": "chrome.exe",
        "visual studio code": "code.exe",
        "vscode": "code.exe",
        "explorateur": "explorer.exe",
        "terminal": "conemu64.exe",
        "cmd": "cmd.exe",
    }

    executable_cible = alias.get(requete_norm)

    fenetres = _fenetres()

    # 1. Correspondance exacte avec l'exécutable
    if executable_cible:
        correspondances = [
            f for f in fenetres
            if normaliser(f[2]) == executable_cible
        ]
    else:
        correspondances = [
            f for f in fenetres
            if normaliser(f[2]) == requete_norm
            or normaliser(f[2]) == requete_norm + ".exe"
        ]

    # 2. Correspondance exacte avec le titre
    if not correspondances:
        correspondances = [
            f for f in fenetres
            if normaliser(f[1]) == requete_norm
        ]

    # 3. Recherche approximative dans les titres
    if not correspondances:
        terminaux = {
            "conemu64.exe",
            "cmd.exe",
            "powershell.exe",
            "windowsterminal.exe",
        }

        correspondances = [
            f for f in fenetres
            if requete_norm in normaliser(f[1])
            and (
                normaliser(f[2]) not in terminaux
                or requete_norm in {
                    "terminal", "cmd", "powershell"
                }
            )
        ]

    if not correspondances:
        LOG.warning(
            "Aucune fenêtre correspondant à : %s",
            requete
        )
        return None

    f = correspondances[0]
    hwnd = f[0]

    u = ctypes.windll.user32

    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)

    u.SetForegroundWindow(hwnd)

    time.sleep(0.3)

    actif = user32.GetForegroundWindow()

    if actif != hwnd:
        LOG.warning(
            "Fenêtre trouvée mais activation non confirmée : "
            "%s (%s), HWND=%s, actif=%s",
            f[1],
            f[2],
            hwnd,
            actif
        )

    return f


def _apps_demarrer():
    if _APPS["liste"] is None:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Get-StartApps | ConvertTo-Json -Compress"], capture_output=True,
                               timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            brut = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
            _APPS["liste"] = brut if isinstance(brut, list) else [brut]
        except Exception:
            _APPS["liste"] = []
    return _APPS["liste"]


def choisir_app(apps, nom):
    q = _sa(nom).strip()
    exact = [a for a in apps if _sa(a.get("Name")) == q]
    partiel = [a for a in apps if q and q in _sa(a.get("Name"))]
    return (exact or sorted(partiel, key=lambda a: len(a.get("Name", ""))) or [None])[0]


def _lancer(nom):
    """Lance une appli (menu Demarrer, Store compris). Renvoie son nom ou None."""
    app = choisir_app(_apps_demarrer(), nom)
    if not app:
        return None
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app['AppID']}"])
    return app["Name"]


def _attendre_fenetre(nom, delai=12.0):
    fin = time.time() + delai
    while time.time() < fin:
        if _activer(nom):
            return True
        time.sleep(0.5)
    return False


# ------------------------------------------------------------------ outils
@outil(
    nom="lancer_application_pc",
    description="Lance N'IMPORTE QUELLE application installee (Spotify, Discord, VS Code, Word, "
                "Steam...) par son nom, puis la met au premier plan. Pour « ouvre Spotify », "
                "« lance Discord ». Pour un SITE web, utilise browser_open.",
    parametres={"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]},
    mcp_expose=False,
)
def lancer_application_pc(nom: str) -> str:
    if _activer(nom):
        return f"{nom} est au premier plan."
    lance = _lancer(nom)
    if not lance:
        return f"Je ne trouve pas d'application « {nom} » sur ce PC."
    _attendre_fenetre(nom)
    return f"{lance} est ouvert."


@outil(
    nom="activer_fenetre",
    description="Met au premier plan une fenetre deja ouverte (par son titre ou son programme) : "
                "« passe sur Spotify », « va sur la fenetre Chrome ».",
    parametres={"type": "object", "properties": {"titre": {"type": "string"}}, "required": ["titre"]},
    mcp_expose=False,
)
def activer_fenetre(titre: str) -> str:
    f = _activer(titre)
    return f"Fenêtre « {f[1][:60]} » au premier plan." if f else f"Je ne trouve pas de fenêtre « {titre} » ouverte."


@outil(
    nom="appuyer_touches",
    description="Appuie sur une touche ou un raccourci clavier dans la fenetre active : « ctrl+l », "
                "« enter », « ctrl+shift+t », « alt+tab », « win+d », « f5 », « echap », « tab ».",
    parametres={"type": "object", "properties": {"combinaison": {"type": "string"}}, "required": ["combinaison"]},
    mcp_expose=False,
)
def appuyer_touches(combinaison: str) -> str:
    try:
        codes = analyser_combinaison(combinaison)
    except ValueError as e:
        return f"Je ne connais pas cette touche ({e})."
    if frozenset(codes) in _INTERDITES:
        return "Je n'appuie pas sur Ctrl+Alt+Suppr."
    _appuyer(codes)
    return f"{combinaison} envoyé."


@outil(
    nom="taper_texte",
    description="Tape du texte au clavier dans le champ actif (accents compris). Pour « ecris ... », "
                "« tape ... ». Jamais de mot de passe, de code bancaire ni de paiement. Mets "
                "entree=true pour valider avec Entree.",
    parametres={"type": "object", "properties": {"texte": {"type": "string"}, "entree": {"type": "boolean"}},
                "required": ["texte"]},
    mcp_expose=False,
)
def taper_texte(texte: str, entree: bool = False) -> str:
    _ecrire(str(texte))
    if entree:
        _appuyer([0x0D])
    return "C'est tapé."


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
    _placer_curseur(c[2], c[3])
    down, up = _BOUTONS["gauche"]
    for _ in range(2 if double else 1):
        _user32.mouse_event(down, 0, 0, 0, 0)
        _user32.mouse_event(up, 0, 0, 0, 0)
        time.sleep(0.08)
    return f"J'ai cliqué sur {c[1][:50]}."


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
            return f"{application} ne s'ouvre pas."
        time.sleep(1.5)                                     # laisse l'interface se construire
    raccourcis = {**_RACCOURCIS_RECHERCHE, **(reglage("controle_pc.recherche_raccourcis", {}) or {})}
    combo = next((v for k, v in raccourcis.items() if k in _sa(application)), "ctrl+f")
    _appuyer(analyser_combinaison(combo))
    time.sleep(0.35)
    _appuyer(analyser_combinaison("ctrl+a"))
    _ecrire(str(requete))
    time.sleep(0.2)
    _appuyer([0x0D])
    return f"J'ai lancé la recherche « {requete} » dans {application}."


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
    "tout en haut": "ctrl+home", "en haut de la page": "ctrl+home", "tout en bas": "ctrl+end",
    "en bas de la page": "ctrl+end",
}
_SITES_RECHERCHE_WEB = {"google", "internet", "le web", "web", "le net", "net", "google chrome"}
_DEICTIQUES = {"ca", "ce", "cela", "ici", "la", "celui ci", "celui la", "ce bouton", "ce lien", "dessus"}
_SANS_TEXTE = ("un ", "une ", "moi", "mon ", "ma ", "a ", "au ", "sur ", "dans ", "pour ", "le ", "la ", "les ")


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
        return "taper_texte", {"texte": " ".join(_tranche(p, orig, m.start(1), len(p)))}

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


def _decouper(phrase):
    return [s.strip(" .!?") for s in _CONNECTEURS.split(str(phrase or "")) if s and s.strip(" .!?")]


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


@outil(
    nom="enchainer_commandes",
    description="Execute plusieurs commandes simples a la suite (« ouvre Chrome puis lance YouTube »). "
                "Chaque etape est une phrase de commande ; s'arrete a la premiere qui echoue.",
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
    dits = []
    for s in list(etapes or [])[:6]:
        d = decider_prioritaire(str(s))
        outil_obj = registre.get(d.outil) if d is not None and d.type == "outil" else None
        if outil_obj is None:
            dits.append(f"Je n'ai pas compris « {s} ».")
            break
        if getattr(outil_obj, "confirmation", False):
            dits.append(f"« {s} » demande une confirmation : dis-le-moi séparément.")
            break
        try:
            res = registre.executer(outil_obj, dict(d.arguments or {}))
        except Exception as exc:
            LOG.exception("enchainer_commandes : %s", s)
            dits.append(message_humain(exc, d.outil))
            break
        texte = str(res or "").strip()
        if texte:
            dits.append(texte)
        time.sleep(float(reglage("controle_pc.pause_etapes", 1.2) or 0))
    return " ".join(dits) or "Rien à faire."
