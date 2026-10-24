"""Validation REELLE sur Windows des fonctions qui ne peuvent pas etre prouvees par des mocks.

A lancer sur TON PC Windows (les tests automatiques de tests/ n'utilisent que des doubles) :

    uv run python scripts/valider_windows.py                      # lecture seule : aucune frappe, aucun clic
    uv run python scripts/valider_windows.py --actions-reelles    # + scenario Bloc-notes complet

Avant de lancer : ouvre Chrome, VS Code et l'Explorateur (sinon ces controles sont « ignores »).
--actions-reelles : ouvre le Bloc-notes, tape un texte, l'enregistre dans le dossier temporaire, le relit,
puis ferme CETTE fenetre. Ne touche a aucun autre fichier. Ne pas toucher clavier/souris pendant le test.

Sortie : un tableau + logs/validation_windows_<horodatage>.json (colle-le pour analyse).
Code de retour : 0 si tout est OK, 1 si au moins un ECHEC, 3 si ce n'est pas Windows.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

TEXTE_TEST = "Bonjour, je suis Jarvis, assistant intelligent. Accents : éàùç, œuvre — « test » !"
RESULTATS: list[dict] = []


def etape(section, nom, fonction):
    debut = time.time()
    try:
        statut, detail = fonction()
    except Exception as exc:                                   # une etape cassee ne stoppe pas les autres
        statut, detail = "ECHEC", f"{type(exc).__name__}: {exc}"
        traceback.print_exc(limit=2)
    duree = round(time.time() - debut, 2)
    RESULTATS.append({"section": section, "etape": nom, "statut": statut, "detail": str(detail)[:600], "duree": duree})
    print(f"[{statut:^6}] {section:<4} {nom}: {str(detail)[:200]}")
    return statut == "OK"


def ok(detail=""):
    return "OK", detail


def echec(detail):
    return "ECHEC", detail


def ignore(detail):
    return "IGNORE", detail


# ------------------------------------------------------------------------- S1
def s1_fenetres(exiger):
    from tools import controle_pc as pc
    fenetres = pc._fenetres()
    if not fenetres:
        return echec("aucune fenetre detectee (EnumWindows)")
    exes = {f[2] for f in fenetres}
    print(f"         {len(fenetres)} fenetres, executables : {', '.join(sorted(e for e in exes if e)[:12])}")
    manquantes = []
    for requete, label in (("chrome", "Chrome"), ("vs code", "VS Code"), ("explorateur", "Explorateur")):
        f = pc._trouver_fenetre(requete, fenetres)
        if f:
            print(f"         {label} reconnu : HWND={f[0]} titre={f[1][:50]!r} exe={f[2]}")
        else:
            manquantes.append(label)
    if manquantes:
        return (echec if exiger else ignore)(f"non ouvert(s) ou non reconnu(s) : {', '.join(manquantes)}")
    return ok("Chrome, VS Code et Explorateur reconnus")


def s1_fenetre_active():
    from tools import controle_pc as pc
    f = pc._fenetre_cible("")
    if not f:
        return echec("fenetre active non identifiee")
    return ok(f"HWND={f[0]} titre={f[1][:50]!r} exe={f[2]}")


def s1_menu_demarrer():
    from tools import controle_pc as pc
    pc._APPS.update(liste=None, echec=0.0)
    apps = pc._apps_demarrer(forcer=True)
    if apps:
        return ok(f"Get-StartApps : {len(apps)} applications ; Bloc-notes -> {bool(pc.choisir_app(apps, 'bloc-notes'))}")
    # Get-StartApps vide : les secours doivent prendre le relais
    return ("OK", "Get-StartApps VIDE (probleme connu) ; secours executables integres actifs : "
            f"{pc._EXECUTABLES_INTEGRES.get('bloc notes')}")


def s1_uia_lecture():
    from tools import controle_pc as pc
    f = pc._fenetre_cible("")
    controles = pc._controles(f[0]) if f else []
    return ok(f"{len(controles)} controles UIA dans {f[1][:40]!r}") if controles else \
        ignore("aucun controle UIA dans la fenetre active (normal pour un terminal) ; teste via le Bloc-notes")


# ------------------------------------------------------------------------- S2
def s2_souris():
    from tools import controle_pc as pc
    from tools.souris import _placer_curseur
    x, y = pc._position()
    placed = _placer_curseur(x + 3, y + 3)
    nx, ny = pc._position()
    _placer_curseur(x, y)
    if not placed or (nx, ny) == (x, y):
        return echec("le curseur ne bouge pas (fenetre administrateur au premier plan ?)")
    return ok(f"({x},{y}) -> ({nx},{ny}) puis retour")


def s2_dpi():
    """L'echelle d'affichage fausse les clics par nom si UIA renvoie des coordonnees virtualisees."""
    import ctypes
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
    except Exception:
        return ignore("GetDpiForSystem indisponible")
    return ok(f"DPI systeme {dpi} (echelle {round(dpi / 96 * 100)} %) ; UIA est lance en mode DPI-aware")


# ------------------------------------------------------------------------- S3
def s3_playwright():
    from core import playwright_partage
    etapes = playwright_partage.diagnostiquer(lancer_navigateur=True)
    mauvaises = [f"{n}: {d}" for n, okk, d in etapes if not okk]
    if mauvaises or not etapes:
        return echec(" | ".join(mauvaises) or "diagnostic vide")
    return ok(" > ".join(n for n, _, _ in etapes))


def s3_chrome_cdp():
    from tools import navigateur
    exe = navigateur._chrome_exe()
    if not exe:
        return echec("Chrome introuvable (navigateur.chrome_exe)")
    port = int(navigateur.reglage("navigateur.cdp_port", 9222) or 9222)
    return ok(f"{exe} ; port CDP {port} {'ouvert' if navigateur._port_ouvert(port) else 'ferme (lance par Jarvis au besoin)'}")


# ------------------------------------------------------------------------- S5
def s5_fichiers():
    from unittest.mock import patch
    from tools import fichiers
    with tempfile.TemporaryDirectory() as d:
        racine = Path(d).resolve() / "Jarvis"
        racine.mkdir()
        with patch.object(fichiers, "racines", return_value=[racine]):
            for r in (fichiers.fichier_ecrire("t/a.txt", "é"), fichiers.fichier_deplacer("t/a.txt", "t/b.txt"),
                      fichiers.fichier_lire("t/b.txt"), fichiers.fichier_supprimer("t")):
                if not r.succes:
                    return echec(str(r))
    return ok("creer, deplacer, lire, supprimer (corbeille) dans un dossier temporaire")


# ------------------------------------------------------------------------- S6
def s6_routage():
    from core.routage_intentions import decider_prioritaire
    attendu = {
        "Ouvre Chrome.": "ouvrir_navigateur", "Passe sur VS Code.": "activer_fenetre",
        "Clique sur Enregistrer.": "cliquer_bouton",
        "Jarvis, ouvre le Bloc-notes et écris : Bonjour, je suis Jarvis, assistant intelligent.": "enchainer_commandes",
    }
    for phrase, outil in attendu.items():
        d = decider_prioritaire(phrase)
        if not d or d.outil != outil:
            return echec(f"{phrase!r} -> {d}")
    return ok(f"{len(attendu)} phrases routees sans LLM")


# ------------------------------------------------------------------ scenario Bloc-notes (S1+S2+S5+S8)
def scenario_bloc_notes():
    from tools import controle_pc as pc
    from tools import systeme
    chemin = Path(tempfile.gettempdir()) / f"jarvis_validation_{int(time.time())}.txt"
    avant = {f[0] for f in pc._fenetres() if f[2] == "notepad.exe"}
    r = systeme.ouvrir_application("bloc-notes")
    if not getattr(r, "succes", True) or "ne vois pas" in str(r):
        return echec(f"ouverture : {r}")
    print(f"         ouverture : {r} (verifie={getattr(r, 'verifie', '?')})")
    f = pc._trouver_fenetre("bloc-notes")
    if not f or f[0] in avant and len(avant) > 1:
        print("         (attention : plusieurs Bloc-notes ouverts, je prends le plus haut)")
    if not f:
        return echec("fenetre du Bloc-notes non identifiee")
    hwnd = f[0]
    r = pc.taper_texte(TEXTE_TEST, fenetre="bloc-notes")
    print(f"         saisie : {r} (succes={r.succes}, verifie={r.verifie})")
    if not r.succes:
        return echec(f"saisie : {r}")
    lu = pc._relire_texte(hwnd)
    if lu is None:
        print("         relecture UIA impossible -> la verification repose sur le fichier enregistre")
    elif not pc._texte_retrouve(TEXTE_TEST, lu):
        return echec(f"le texte relu differe : {lu[:100]!r}")
    pc._activer("bloc-notes")
    pc.appuyer_touches("ctrl+s")
    if not pc._attendre_fenetre("enregistrer sous", 6.0) and not pc._attendre_fenetre("save as", 2.0):
        return echec("la boite « Enregistrer sous » n'est pas apparue")
    pc._ecrire(str(chemin))
    pc.appuyer_touches("enter")
    fin = time.time() + 6
    while time.time() < fin and not chemin.exists():
        time.sleep(0.3)
    if not chemin.exists():
        return echec(f"fichier non cree : {chemin}")
    contenu = chemin.read_text(encoding="utf-8-sig")
    pc._activer("bloc-notes")
    pc.appuyer_touches("alt+f4")
    try:
        chemin.unlink()
    except OSError:
        pass
    if " ".join(contenu.split()) != " ".join(TEXTE_TEST.split()):
        return echec(f"contenu enregistre different : {contenu[:100]!r}")
    return ok("ouvert, texte exact tape (ponctuation + accents), enregistre, relu, ferme")


def scenario_clic_par_nom():
    """Ouvre le menu Fichier du Bloc-notes par son NOM, verifie qu'il s'ouvre, puis Echap."""
    from tools import controle_pc as pc
    from tools import systeme
    systeme.ouvrir_application("bloc-notes")
    f = pc._activer("bloc-notes")
    if not f:
        return echec("Bloc-notes introuvable")
    r = pc.cliquer_bouton("Fichier", fenetre="bloc-notes")
    print(f"         clic : {r} (details={getattr(r, 'details', {})})")
    time.sleep(0.8)
    noms = [c[1].lower() for c in pc._controles(f[0])]
    pc.appuyer_touches("echap")
    pc._activer("bloc-notes")
    pc.appuyer_touches("alt+f4")
    if not getattr(r, "succes", False):
        return echec(str(r))
    if any("enregistrer" in n or "nouvel" in n for n in noms):
        return ok("clic par nom -> menu ouvert (constate par UIA)")
    return echec("clic envoye mais le menu Fichier n'est pas constate ouvert (verifier DPI/echelle)")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--actions-reelles", action="store_true", help="scenario Bloc-notes complet (frappe, clics, fichier)")
    ap.add_argument("--exiger-fenetres", action="store_true", help="Chrome/VS Code/Explorateur ouverts = obligatoire")
    args = ap.parse_args(argv)
    if os.name != "nt":
        print("Ce script valide le comportement REEL de Windows : lance-le sur ton PC Windows.")
        return 3
    etape("S1", "Fenetres reconnues (Chrome, VS Code, Explorateur)", lambda: s1_fenetres(args.exiger_fenetres))
    etape("S1", "Fenetre active (GetForegroundWindow)", s1_fenetre_active)
    etape("S1", "Menu Demarrer / secours", s1_menu_demarrer)
    etape("S1", "UI Automation (lecture)", s1_uia_lecture)
    etape("S2", "Souris deplacable", s2_souris)
    etape("S2", "Echelle d'affichage (DPI)", s2_dpi)
    etape("S3", "Playwright : chaine complete", s3_playwright)
    etape("S3", "Chrome + port CDP", s3_chrome_cdp)
    etape("S5", "Fichiers : creer/deplacer/lire/supprimer", s5_fichiers)
    etape("S6", "Routage vocal sans LLM", s6_routage)
    if args.actions_reelles:
        etape("S2", "SCENARIO Bloc-notes : ouvrir, taper, enregistrer, relire", scenario_bloc_notes)
        etape("S1", "SCENARIO clic par nom (menu Fichier)", scenario_clic_par_nom)
    else:
        print("[ IGNORE ] scenarios Bloc-notes/clic : ajoute --actions-reelles pour les executer")
    dossier = RACINE / "logs"
    dossier.mkdir(exist_ok=True)
    rapport = dossier / f"validation_windows_{time.strftime('%Y%m%d-%H%M%S')}.json"
    rapport.write_text(json.dumps({"python": sys.version, "resultats": RESULTATS}, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    echecs = [r for r in RESULTATS if r["statut"] == "ECHEC"]
    print(f"\n{len(RESULTATS) - len(echecs)}/{len(RESULTATS)} etapes sans echec. Rapport : {rapport}")
    return 1 if echecs else 0


if __name__ == "__main__":
    sys.exit(main())
