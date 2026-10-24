"""Auto-modification encadree du code de Jarvis (S9 du plan de correction).

Principe : Jarvis ne modifie JAMAIS sa propre branche de travail a chaud. Toute modification suit
le cycle  branche dediee -> ecriture -> diff -> tests -> commit (seulement si les tests passent)
-> redemarrage supervise -> retour arriere automatique en cas d'echec.

Ce module ne fait rien tout seul et n'est PAS un outil vocal : il fournit les briques (et
``scripts/auto_modif.py`` une ligne de commande) pour qu'une modification soit toujours
identifiable, testee et annulable. Aucune fusion automatique : la branche reste a relire.

Garde-fous :
- arbre de travail propre exige au depart (rien de l'utilisatrice n'est ecrase) ;
- chemins proteges (config.yaml, .env, secrets, .git, ce module, les verrous de permissions) ;
- jamais de shell : git et les tests sont lances avec une liste d'arguments.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from pathlib import Path

LOG = logging.getLogger("jarvis.auto_modification")

# Fichiers qu'une auto-modification ne doit jamais toucher : secrets, donnees personnelles, et
# les fichiers qui portent les verrous de securite (un test ne doit pas pouvoir les « assouplir »).
PROTEGES_EXACTS = {
    "config.yaml", ".env", "core/auto_modification.py", "scripts/auto_modif.py",
    "core/registre.py", "core/confidentialite.py", "core/confirmation_vocale.py",
}
PROTEGES_PREFIXES = (".git/", ".claude/", "notes/", "logs/", "memoire", "finances/", "secrets/")
COMMANDE_TESTS = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests"]
COMMANDE_COMPILATION = [sys.executable, "-m", "compileall", "-q", "core", "tools", "jarvis14.py"]


class ErreurAutoModif(RuntimeError):
    """Operation refusee ou echouee ; le message est lisible par l'utilisateur."""


def _git(racine, *args, check=True):
    r = subprocess.run(["git", *args], cwd=str(racine), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    if check and r.returncode != 0:
        raise ErreurAutoModif(f"git {' '.join(args[:2])} a echoue : {(r.stderr or r.stdout).strip()[:300]}")
    return r


def _fichier_etat(racine) -> Path:
    return Path(racine) / "logs" / "auto_modif" / "etat.json"


def _sauver(racine, etat):
    f = _fichier_etat(racine)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(etat, ensure_ascii=False, indent=2), encoding="utf-8")


def charger_etat(racine):
    try:
        return json.loads(_fichier_etat(racine).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def chemin_relatif(racine, chemin) -> str:
    """Chemin relatif normalise (« / ») ; ErreurAutoModif s'il sort du depot."""
    racine = Path(racine).resolve()
    cible = (racine / chemin).resolve() if not Path(chemin).is_absolute() else Path(chemin).resolve()
    try:
        return cible.relative_to(racine).as_posix()
    except ValueError:
        raise ErreurAutoModif(f"« {chemin} » est en dehors du projet.") from None


def chemin_autorise(racine, chemin) -> bool:
    try:
        rel = chemin_relatif(racine, chemin)
    except ErreurAutoModif:
        return False
    bas = rel.lower()
    if bas in PROTEGES_EXACTS or any(bas.startswith(p) for p in PROTEGES_PREFIXES):
        return False
    return not any(m in bas for m in ("secret", "credential", ".env", "token"))


def arbre_propre(racine) -> bool:
    """Aucun changement non commite sur les fichiers suivis."""
    return not _git(racine, "status", "--porcelain", "--untracked-files=no").stdout.strip()


def demarrer(racine, nom: str) -> dict:
    """Cree la branche dediee depuis l'etat courant et memorise le point de retour."""
    racine = Path(racine)
    if charger_etat(racine) and charger_etat(racine).get("actif"):
        raise ErreurAutoModif("Une auto-modification est deja en cours : termine-la ou annule-la d'abord.")
    if not arbre_propre(racine):
        raise ErreurAutoModif("Le projet a des modifications non enregistrees : commit ou stash avant de "
                              "laisser Jarvis se modifier.")
    base = _git(racine, "rev-parse", "HEAD").stdout.strip()
    origine = _git(racine, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    slug = "".join(c if c.isalnum() else "-" for c in nom.lower()).strip("-")[:30] or "modif"
    branche = f"jarvis/auto-{slug}-{time.strftime('%Y%m%d-%H%M%S')}"
    _git(racine, "switch", "-c", branche)
    etat = {"actif": True, "branche": branche, "origine": origine, "base": base,
            "fichiers": [], "nouveaux": [], "tests_ok": None, "commit": ""}
    _sauver(racine, etat)
    LOG.info("auto-modification demarree : %s (base %s)", branche, base[:8])
    return etat


def ecrire_fichier(racine, chemin, contenu: str) -> dict:
    """Ecrit un fichier du projet (hors chemins proteges) et l'enregistre dans l'etat."""
    racine = Path(racine)
    etat = charger_etat(racine)
    if not etat or not etat.get("actif"):
        raise ErreurAutoModif("Aucune auto-modification active : appelle demarrer() d'abord.")
    if not chemin_autorise(racine, chemin):
        raise ErreurAutoModif(f"« {chemin} » est protege : je ne le modifie pas.")
    rel = chemin_relatif(racine, chemin)
    cible = racine / rel
    existait = cible.exists()
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(contenu, encoding="utf-8")
    if rel not in etat["fichiers"]:
        etat["fichiers"].append(rel)
    if not existait and rel not in etat["nouveaux"]:
        etat["nouveaux"].append(rel)
    etat["tests_ok"] = None                    # toute nouvelle ecriture invalide la validation precedente
    _sauver(racine, etat)
    return etat


def diff(racine) -> str:
    """Diff complet de la modification par rapport au point de depart (fichiers nouveaux inclus)."""
    etat = charger_etat(racine)
    if not etat:
        raise ErreurAutoModif("Aucune auto-modification en cours.")
    if etat["nouveaux"]:
        _git(racine, "add", "-N", "--", *etat["nouveaux"])
    return _git(racine, "diff", etat["base"], "--", *(etat["fichiers"] or ["."])).stdout


def valider(racine, commandes=None, timeout=900):
    """Compile puis lance les tests. Renvoie (ok, sortie). L'etat memorise le verdict."""
    racine = Path(racine)
    etat = charger_etat(racine)
    if not etat or not etat.get("actif"):
        raise ErreurAutoModif("Aucune auto-modification active.")
    sortie, ok = [], True
    for cmd in (commandes if commandes is not None else [COMMANDE_COMPILATION, COMMANDE_TESTS]):
        try:
            r = subprocess.run(cmd, cwd=str(racine), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok = False
            sortie.append(f"{cmd[:3]} : {exc}")
            break
        sortie.append((r.stdout + r.stderr)[-1500:])
        if r.returncode != 0:
            ok = False
            break
    etat["tests_ok"] = ok
    _sauver(racine, etat)
    return ok, "\n".join(sortie)


def enregistrer(racine, message: str) -> str:
    """Commit sur la branche dediee, UNIQUEMENT si la derniere validation est verte."""
    racine = Path(racine)
    etat = charger_etat(racine)
    if not etat or not etat.get("actif"):
        raise ErreurAutoModif("Aucune auto-modification active.")
    if etat.get("tests_ok") is not True:
        raise ErreurAutoModif("Les tests n'ont pas ete lances ou ont echoue : je n'enregistre pas.")
    _git(racine, "add", "--", *etat["fichiers"])
    _git(racine, "commit", "-m", message)
    etat["commit"] = _git(racine, "rev-parse", "HEAD").stdout.strip()
    _sauver(racine, etat)
    return etat["commit"]


def annuler(racine) -> dict:
    """Retour arriere complet : le projet retrouve EXACTEMENT son etat de depart."""
    racine = Path(racine)
    etat = charger_etat(racine)
    if not etat or not etat.get("actif"):
        raise ErreurAutoModif("Aucune auto-modification a annuler.")
    _git(racine, "reset", "--hard", etat["base"])
    for rel in etat["nouveaux"]:
        try:
            (racine / rel).unlink()
        except OSError:
            pass
    _git(racine, "switch", etat["origine"])
    _git(racine, "branch", "-D", etat["branche"], check=False)
    etat["actif"] = False
    _sauver(racine, etat)
    LOG.info("auto-modification annulee : retour a %s", etat["base"][:8])
    return etat


def terminer(racine) -> dict:
    """Ferme la session SANS fusionner : revient a la branche d'origine, la branche de travail reste a relire."""
    racine = Path(racine)
    etat = charger_etat(racine)
    if not etat or not etat.get("actif"):
        raise ErreurAutoModif("Aucune auto-modification active.")
    if not etat.get("commit"):
        raise ErreurAutoModif("Rien n'a ete enregistre : utilise annuler() ou enregistre d'abord.")
    _git(racine, "switch", etat["origine"])
    etat["actif"] = False
    _sauver(racine, etat)
    return etat


def redemarrage_supervise(commande, delai=10.0, sante=None):
    """Lance `commande` et verifie qu'elle tient `delai` secondes (et que `sante()` est vrai).

    Renvoie (ok, detail). Le processus est arrete ensuite ; l'appelant decide du retour arriere.
    """
    try:
        proc = subprocess.Popen(commande, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except OSError as exc:
        return False, f"lancement impossible : {exc}"
    fin = time.time() + delai
    try:
        while time.time() < fin:
            if proc.poll() is not None:
                err = (proc.stderr.read() or b"").decode("utf-8", "replace")[-300:]
                return False, f"le processus s'est arrete (code {proc.returncode}) : {err}"
            time.sleep(0.2)
        if sante is not None and not sante():
            return False, "le test de sante a echoue"
        return True, "le processus tourne toujours apres le delai"
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                proc.kill()
