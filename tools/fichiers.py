"""Operations sur fichiers confinees a des racines autorisees (S5 du plan de correction).

Aucun outil de fichiers n'existait : le LLM n'avait que le clavier/la souris pour creer un fichier.
Ces outils sont volontairement prudents :

- chemins normalises et CONFINES : tout chemin est resolu (symlinks compris) et doit rester dans une
  racine autorisee (config ``fichiers.racines``, sinon ~/Documents/Jarvis) ;
- ecriture ATOMIQUE (fichier temporaire + os.replace) ; l'ancienne version est sauvegardee en ``.bak`` ;
- suppression = DEPLACEMENT dans ``.corbeille_jarvis`` de la racine (recuperable), N3 : confirmation
  toujours, jamais « toujours autoriser », jamais a distance ;
- jamais de fichier de secrets (config.yaml, .env, cles...), jamais exposes au MCP.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from core.config import reglage
from core.registre import outil
from core.resultat import ResultatOutil

LOG = logging.getLogger("jarvis.fichiers")
CORBEILLE = ".corbeille_jarvis"
TAILLE_MAX_LECTURE = 200_000
_INTERDITS = ("config.yaml", ".env", "id_rsa", "id_ed25519", "credentials", "token.json", ".pem", ".key")


class ErreurFichier(Exception):
    """Refus ou echec explicable a l'utilisateur."""


def racines():
    brutes = reglage("fichiers.racines", None) or [str(Path.home() / "Documents" / "Jarvis")]
    return [Path(os.path.expandvars(str(r))).expanduser() for r in brutes]


def resoudre(chemin, racines_=None) -> Path:
    """Chemin absolu resolu, garanti DANS une racine autorisee. Un chemin relatif part de la 1re racine."""
    chemin = str(chemin or "").strip().strip('"')
    if not chemin:
        raise ErreurFichier("Il me faut un chemin.")
    if chemin.startswith("\\\\") or chemin.startswith("//"):
        raise ErreurFichier("Je ne touche pas aux partages reseau.")
    liste = [r.resolve() for r in (racines_ or racines())]
    p = Path(os.path.expandvars(chemin)).expanduser()
    if not p.is_absolute():
        p = liste[0] / p
    cible = p.resolve()                       # resout .., liens symboliques et casse
    if not any(cible == r or r in cible.parents for r in liste):
        raise ErreurFichier("Ce chemin est en dehors des dossiers que je suis autorise a modifier.")
    if CORBEILLE in cible.parts:
        raise ErreurFichier("Ce dossier est la corbeille de Jarvis.")
    bas = cible.name.lower()
    if any(m in bas for m in _INTERDITS):
        raise ErreurFichier("Je ne touche pas aux fichiers de secrets ou de configuration.")
    return cible


def ecrire_atomique(cible: Path, contenu: str, ajouter=False) -> dict:
    """Ecrit via un fichier temporaire puis os.replace ; sauvegarde l'ancien contenu en .bak."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    ancien = cible.read_text(encoding="utf-8") if cible.exists() and cible.is_file() else None
    final = (ancien or "") + contenu if ajouter else contenu
    sauvegarde = None
    if ancien is not None:
        sauvegarde = cible.with_name(cible.name + ".bak")
        sauvegarde.write_text(ancien, encoding="utf-8")
    fd, tmp = tempfile.mkstemp(prefix=cible.name + ".", suffix=".tmp", dir=str(cible.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(final)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, cible)                # atomique : jamais de fichier a moitie ecrit
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"octets": len(final.encode("utf-8")), "sauvegarde": str(sauvegarde) if sauvegarde else ""}


def _verifie_relu(cible: Path, attendu: str) -> bool:
    try:
        return cible.read_text(encoding="utf-8") == attendu
    except (OSError, UnicodeDecodeError):
        return False


def _echec(exc):
    return ResultatOutil(str(exc), succes=False, erreur="refus" if isinstance(exc, ErreurFichier) else "erreur")


@outil(
    nom="fichier_lister",
    description="Liste le contenu d'un dossier autorise (par defaut le dossier de travail de Jarvis, "
                "Documents/Jarvis). Pour « qu'est-ce qu'il y a dans mon dossier Jarvis ».",
    parametres={"type": "object", "properties": {"dossier": {"type": "string"}}},
)
def fichier_lister(dossier: str = ".") -> str:
    try:
        d = resoudre(dossier or ".")
        if not d.is_dir():
            return ResultatOutil(f"« {d.name} » n'est pas un dossier.", succes=False, erreur="introuvable")
        noms = sorted(p.name + ("/" if p.is_dir() else "") for p in d.iterdir() if p.name != CORBEILLE)
    except (ErreurFichier, OSError) as exc:
        return _echec(exc)
    return ResultatOutil("Contenu : " + (", ".join(noms[:40]) or "vide") + ".", succes=True, verifie=True,
                         details={"dossier": str(d), "elements": len(noms)})


@outil(
    nom="fichier_lire",
    description="Lit un fichier texte d'un dossier autorise (200 Ko max). Pour « lis le fichier notes.txt ».",
    parametres={"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]},
)
def fichier_lire(chemin: str) -> str:
    try:
        p = resoudre(chemin)
        if not p.is_file():
            return ResultatOutil(f"Le fichier « {p.name} » n'existe pas.", succes=False, erreur="introuvable")
        if p.stat().st_size > TAILLE_MAX_LECTURE:
            return ResultatOutil(f"« {p.name} » est trop gros pour que je le lise ici.", succes=False, erreur="taille")
        texte = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ResultatOutil("Ce fichier n'est pas du texte lisible.", succes=False, erreur="format")
    except (ErreurFichier, OSError) as exc:
        return _echec(exc)
    return ResultatOutil(texte, succes=True, verifie=True, details={"chemin": str(p), "octets": len(texte)})


def _annonce_ecriture(args):
    return f"Je vais ecrire dans le fichier {str((args or {}).get('chemin', '?'))[:120]}."


@outil(
    nom="fichier_ecrire",
    description="Cree ou modifie un fichier texte dans un dossier autorise. Ecriture atomique, ancienne "
                "version sauvegardee en .bak, resultat RELU pour verification. ajouter=true complete le "
                "fichier au lieu de le remplacer. Pour « cree un fichier notes.txt avec ... ».",
    parametres={"type": "object", "properties": {
        "chemin": {"type": "string"}, "contenu": {"type": "string"}, "ajouter": {"type": "boolean"}},
        "required": ["chemin", "contenu"]},
    confirmation=True,
    annonce=_annonce_ecriture,
)
def fichier_ecrire(chemin: str, contenu: str, ajouter: bool = False) -> str:
    try:
        p = resoudre(chemin)
        if p.exists() and not p.is_file():
            return ResultatOutil(f"« {p.name} » n'est pas un fichier.", succes=False, erreur="type")
        avant = p.read_text(encoding="utf-8") if p.exists() else ""
        infos = ecrire_atomique(p, str(contenu), ajouter=bool(ajouter))
        ok = _verifie_relu(p, avant + str(contenu) if ajouter else str(contenu))
    except UnicodeDecodeError:
        return ResultatOutil("Le fichier existant n'est pas du texte : je ne l'ecrase pas.", succes=False, erreur="format")
    except (ErreurFichier, OSError) as exc:
        return _echec(exc)
    if not ok:
        return ResultatOutil(f"J'ai ecrit « {p.name} » mais la relecture ne correspond pas.",
                             succes=False, verifie=True, details={"chemin": str(p), **infos}, erreur="verification")
    return ResultatOutil(f"Le fichier « {p.name} » est ecrit et verifie.", succes=True, verifie=True,
                         details={"chemin": str(p), **infos})


def _annonce_deplacement(args):
    a = args or {}
    return f"Je vais deplacer {str(a.get('source', '?'))[:80]} vers {str(a.get('destination', '?'))[:80]}."


@outil(
    nom="fichier_deplacer",
    description="Deplace ou renomme un fichier/dossier a l'interieur des dossiers autorises. Refuse d'ecraser "
                "une destination existante.",
    parametres={"type": "object", "properties": {"source": {"type": "string"}, "destination": {"type": "string"}},
                "required": ["source", "destination"]},
    confirmation=True,
    annonce=_annonce_deplacement,
)
def fichier_deplacer(source: str, destination: str) -> str:
    try:
        src, dst = resoudre(source), resoudre(destination)
        if not src.exists():
            return ResultatOutil(f"« {src.name} » n'existe pas.", succes=False, erreur="introuvable")
        if dst.exists():
            return ResultatOutil(f"« {dst.name} » existe deja : je ne l'ecrase pas.", succes=False, erreur="existe")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    except (ErreurFichier, OSError) as exc:
        return _echec(exc)
    ok = dst.exists() and not src.exists()
    return ResultatOutil(f"« {src.name} » est deplace." if ok else "Le deplacement n'est pas confirme.",
                         succes=ok, verifie=True, details={"source": str(src), "destination": str(dst)},
                         erreur="" if ok else "verification")


def _annonce_suppression(args):
    return (f"Je vais mettre {str((args or {}).get('chemin', '?'))[:120]} a la corbeille de Jarvis "
            "(recuperable).")


@outil(
    nom="fichier_supprimer",
    description="Supprime un fichier ou un dossier d'un dossier autorise en le DEPLACANT dans la corbeille de "
                "Jarvis (recuperable). Action critique : confirmation toujours demandee.",
    parametres={"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]},
    confirmation=True,
    annonce=_annonce_suppression,
)
def fichier_supprimer(chemin: str) -> str:
    try:
        p = resoudre(chemin)
        if p in [r.resolve() for r in racines()]:
            return ResultatOutil("Je ne supprime pas une racine entiere.", succes=False, erreur="refus")
        if not p.exists():
            return ResultatOutil(f"« {p.name} » n'existe pas.", succes=False, erreur="introuvable")
        racine = next(r.resolve() for r in racines() if r.resolve() == p or r.resolve() in p.parents)
        corbeille = racine / CORBEILLE
        corbeille.mkdir(exist_ok=True)
        dest = corbeille / f"{time.strftime('%Y%m%d-%H%M%S')}-{p.name}"
        shutil.move(str(p), str(dest))
    except (ErreurFichier, OSError) as exc:
        return _echec(exc)
    ok = dest.exists() and not p.exists()
    return ResultatOutil(f"« {p.name} » est a la corbeille de Jarvis." if ok else "La suppression n'est pas confirmee.",
                         succes=ok, verifie=True, details={"corbeille": str(dest)}, erreur="" if ok else "verification")
