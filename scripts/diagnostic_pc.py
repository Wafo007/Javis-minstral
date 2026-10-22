"""Diagnostic du controle du PC : verifie chaque capacite SUR TA MACHINE et dit ce qui marche.

Usage :  uv run python scripts/diagnostic_pc.py
Aucune action destructrice : la souris bouge de 2 pixels puis revient, aucune touche n'est envoyee,
rien n'est clique ni tape. Copie-colle le resultat si une ligne est en echec.
"""
import ctypes
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
RESULTATS = []


def test(nom, fonction):
    try:
        detail = fonction()
        RESULTATS.append((nom, True, detail))
        print(f"[ OK ] {nom}: {detail}")
    except Exception as e:
        RESULTATS.append((nom, False, f"{type(e).__name__}: {e}"))
        print(f"[FAIL] {nom}: {type(e).__name__}: {e}")


def t_windows():
    assert os.name == "nt", "ce diagnostic est pour Windows"
    return f"Python {sys.version.split()[0]}"


def t_fenetres():
    from tools import controle_pc as pc
    f = pc._fenetres()
    assert f, "aucune fenetre detectee"
    return f"{len(f)} fenetres, ex. : " + ", ".join(sorted({x[2] for x in f if x[2]})[:6])


def t_premier_plan():
    """
    Vérifie que Jarvis peut identifier la fenêtre
    actuellement active sur Windows.
    """

    from tools import controle_pc as pc

    # Utiliser la nouvelle méthode de contrôle Windows
    fenetre = pc._fenetre_cible("")

    # Le diagnostic doit échouer si aucune fenêtre
    # active n'est détectée.
    assert fenetre is not None, (
        "Impossible d'identifier la fenêtre active Windows."
    )

    hwnd, titre, executable = fenetre

    # Vérifier la validité des informations
    assert hwnd, "Handle de fenêtre invalide."

    assert titre or executable, (
        "Fenêtre détectée mais aucune information disponible."
    )

    return (
        f"fenetre active : {titre[:50]!r} "
        f"({executable}) | HWND={hwnd}"
    )

def t_menu_demarrer():
    from tools import controle_pc as pc
    apps = pc._apps_demarrer()
    assert apps, "Get-StartApps ne renvoie rien (PowerShell bloque ?)"
    trouves = {n: bool(pc.choisir_app(apps, n)) for n in ("chrome", "firefox", "edge", "spotify", "discord")}
    return f"{len(apps)} applications ; trouvees : " + ", ".join(n for n, ok in trouves.items() if ok)


def t_uia():
    from tools import controle_pc as pc
    f = pc._fenetre_cible("")
    assert f, "pas de fenetre active"
    c = pc._controles(f[0])
    return f"{len(c)} controles lisibles dans {f[1][:40]!r}" + ("" if c else " (fenetre sans UI Automation : le clic par nom se rabattra sur la vision)")


def t_souris():
    from tools import controle_pc as pc
    from tools.souris import _placer_curseur
    x, y = pc._position()
    assert _placer_curseur(x + 2, y + 2), "SetCursorPos a echoue"
    nx, ny = pc._position()
    _placer_curseur(x, y)
    assert (nx, ny) != (x, y), "le curseur n'a pas bouge (fenetre admin au premier plan ?)"
    return f"curseur a ({x},{y}) -> deplacable"


def t_capture():
    from tools import ecran
    r = ecran.capture_screen(0)
    assert isinstance(r, dict), str(r)
    return r["apercu"]


def t_clavier():
    from tools import controle_pc as pc
    assert pc.analyser_combinaison("ctrl+shift+t") and pc._VK["win"]
    assert hasattr(ctypes.windll.user32, "SendInput") and hasattr(ctypes.windll.user32, "keybd_event")
    return "API clavier presentes (aucune touche envoyee)"


def t_routeur():
    from tools import controle_pc as pc
    attendu = {"clique sur Enregistrer": "cliquer_bouton", "cherche Daft Punk sur Spotify": "rechercher_dans_application",
               "ouvre Chrome et lance YouTube": "enchainer_commandes", "double clic": "souris_clic"}
    for phrase, outil in attendu.items():
        r = pc.router_commande_pc(phrase)
        assert r and r[0] == outil, f"{phrase!r} -> {r}"
    return "4 phrases routees sans LLM"


def t_chrome():
    from tools import navigateur
    exe = navigateur._chrome_exe()
    assert exe, "Chrome introuvable : renseigne navigateur.chrome_exe dans config.yaml"
    return exe


def t_playwright():
    import playwright  # noqa: F401
    return "module playwright present"


def t_cdp():
    from tools import navigateur
    port = int(navigateur.reglage("navigateur.cdp_port", 9222) or 9222)
    return f"port {port} " + ("OUVERT (Chrome dedie deja lance)" if navigateur._port_ouvert(port) else
                              "ferme (normal : Jarvis lancera le Chrome dedie tout seul)")


def t_vision():
    from core import cloud
    four = cloud.fournisseur()
    assert four, "aucun fournisseur cloud"
    if four == "mistral":
        assert cloud.client_mistral() is not None, "mistral.cle absente"
        return f"fournisseur mistral, modele de vision : {cloud.modele_vision_mistral()}"
    return f"fournisseur {four}"


def t_config():
    from core.config import reglage
    problemes = []
    for chemin in ("openai.cle", "anthropic.cle"):
        v = str(reglage(chemin, "") or "")
        if v.endswith("..."):
            problemes.append(f"{chemin} est un placeholder (lance scripts/adapter_config.py)")
    assert not problemes, " ; ".join(problemes)
    return "pas de cle placeholder"


for nom, f in (("Windows", t_windows), ("Config", t_config), ("Fenetres visibles", t_fenetres),
               ("Fenetre active", t_premier_plan), ("Menu Demarrer", t_menu_demarrer),
               ("UI Automation (clic par nom)", t_uia), ("Souris", t_souris), ("Capture d'ecran", t_capture),
               ("Clavier", t_clavier), ("Routeur de commandes", t_routeur), ("Chrome installe", t_chrome),
               ("Playwright", t_playwright), ("Port Chrome dedie", t_cdp), ("Vision (cloud)", t_vision)):
    test(nom, f)

echecs = [n for n, ok, _ in RESULTATS if not ok]
print("\n" + ("Tout est OK." if not echecs else f"{len(echecs)} point(s) a corriger : " + ", ".join(echecs)))
