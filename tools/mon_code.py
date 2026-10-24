"""Auto-modification du code de Jarvis par la voix, ENCADREE (S9 du plan de correction).

Jarvis peut lire son code et le modifier, mais jamais « a chaud » ni sans trace :
branche git dediee -> ecriture -> diff -> tests -> commit (seulement si les tests passent).
Rien n'est fusionne : la branche ``jarvis/auto-...`` reste a relire, et ``code_modification_annuler``
ramene le projet EXACTEMENT a son etat de depart.

Garde-fous (core/auto_modification.py) : config.yaml, .env, secrets, .git, les verrous de permissions
(core/registre.py, confirmation_vocale.py, confidentialite.py) et le module d'auto-modification
lui-meme sont INTERDITS en ecriture et en lecture. Le commit est une action N3 (confirmation chaque fois).
"""
from __future__ import annotations

from pathlib import Path

from core import auto_modification as am
from core.registre import outil
from core.resultat import ResultatOutil

RACINE = Path(__file__).resolve().parent.parent
_EXTENSIONS = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".html", ".toml", ".bat", ".ps1", ".css", ".js"}
_LECTURE_MAX = 30_000


def _err(exc) -> ResultatOutil:
    return ResultatOutil(str(exc), succes=False, erreur="auto_modification")


@outil(
    nom="code_lister",
    description="Liste les fichiers du code de Jarvis (dossier optionnel : core, tools, tests...). Pour « montre-moi "
                "ton code », « quels fichiers te composent ». Ne liste jamais les secrets.",
    parametres={"type": "object", "properties": {"dossier": {"type": "string"}}},
)
def code_lister(dossier: str = "") -> str:
    try:
        base = RACINE / am.chemin_relatif(RACINE, dossier or ".")
    except am.ErreurAutoModif as exc:
        return _err(exc)
    fichiers = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix in _EXTENSIONS and "__pycache__" not in p.parts \
                and ".venv" not in p.parts and am.chemin_autorise(RACINE, p):
            fichiers.append(p.relative_to(RACINE).as_posix())
    return "\n".join(fichiers[:300]) or "Aucun fichier."


@outil(
    nom="code_lire",
    description="Lit un fichier du code de Jarvis (chemin relatif au projet, ex. tools/controle_pc.py) pour l'examiner "
                "avant de le modifier. Refuse config.yaml, .env et tout secret.",
    parametres={"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]},
)
def code_lire(chemin: str) -> str:
    if not am.chemin_autorise(RACINE, chemin):
        return ResultatOutil(f"« {chemin} » est protege : je ne le lis pas.", succes=False, erreur="protege")
    cible = RACINE / am.chemin_relatif(RACINE, chemin)
    if cible.suffix not in _EXTENSIONS or not cible.is_file():
        return ResultatOutil(f"Je ne trouve pas de fichier de code « {chemin} ».", succes=False, erreur="introuvable")
    texte = cible.read_text(encoding="utf-8", errors="replace")
    suite = f"\n[... tronque : {len(texte)} caracteres au total]" if len(texte) > _LECTURE_MAX else ""
    return texte[:_LECTURE_MAX] + suite


def _annonce_demarrage(args):
    return f"Je vais creer une branche de travail pour modifier mon code : {(args or {}).get('nom', 'modification')}."


@outil(
    nom="code_modification_demarrer",
    description="Demarre une modification de TON PROPRE code : cree une branche git dediee et memorise le point de retour. "
                "A appeler avant code_modification_ecrire. Refuse si le projet a des changements non commites.",
    parametres={"type": "object", "properties": {"nom": {"type": "string", "description": "Nom court de la modification."}},
                "required": ["nom"]},
    confirmation=True, annonce=_annonce_demarrage,
)
def code_modification_demarrer(nom: str) -> str:
    try:
        etat = am.demarrer(RACINE, nom)
    except am.ErreurAutoModif as exc:
        return _err(exc)
    return ResultatOutil(f"Branche de travail creee : {etat['branche']}.", succes=True, verifie=True)


def _annonce_ecriture(args):
    return f"Je vais ecrire le fichier {(args or {}).get('chemin', '')} sur la branche de travail."


@outil(
    nom="code_modification_ecrire",
    description="Ecrit (remplace) UN fichier de ton code sur la branche de modification (contenu COMPLET du fichier). "
                "Lis-le d'abord avec code_lire. Refuse les fichiers proteges (secrets, verrous de securite). "
                "Apres l'ecriture : code_modification_tester, puis code_modification_enregistrer.",
    parametres={"type": "object", "properties": {"chemin": {"type": "string"},
                                                   "contenu": {"type": "string", "description": "Contenu complet du fichier."}},
                "required": ["chemin", "contenu"]},
    confirmation=True, annonce=_annonce_ecriture,
)
def code_modification_ecrire(chemin: str, contenu: str) -> str:
    try:
        am.ecrire_fichier(RACINE, chemin, contenu)
    except am.ErreurAutoModif as exc:
        return _err(exc)
    return ResultatOutil(f"Fichier {chemin} ecrit sur la branche de travail. Les tests restent a lancer.",
                         succes=True, verifie=True)


@outil(
    nom="code_modification_diff",
    description="Montre le diff de la modification en cours (ce qui change par rapport au point de depart).",
    parametres={"type": "object", "properties": {}},
)
def code_modification_diff() -> str:
    try:
        d = am.diff(RACINE)
    except am.ErreurAutoModif as exc:
        return _err(exc)
    return (d[:8000] + ("\n[... diff tronque]" if len(d) > 8000 else "")) or "Aucun changement."


@outil(
    nom="code_modification_tester",
    description="Compile le code puis lance TOUS les tests sur la branche de modification. Le commit n'est possible "
                "que si c'est vert. Peut durer plusieurs minutes.",
    parametres={"type": "object", "properties": {}},
    lent=True, phrase_attente="Je lance les tests, cela peut prendre quelques minutes.",
)
def code_modification_tester() -> str:
    try:
        ok, sortie = am.valider(RACINE)
    except am.ErreurAutoModif as exc:
        return _err(exc)
    fin = sortie[-800:]
    if ok:
        return ResultatOutil("Compilation et tests : tout est vert.\n" + fin, succes=True, verifie=True)
    return ResultatOutil("Les tests ont echoue : je n'enregistre rien.\n" + fin, succes=False, verifie=True,
                         erreur="tests")


def _annonce_commit(args):
    return "Je vais enregistrer la modification sur la branche de travail (les tests sont verts)."


@outil(
    nom="code_modification_enregistrer",
    description="Enregistre (commit) la modification sur la branche dediee. Uniquement si les tests sont verts. "
                "Action critique : confirmation a chaque fois. Rien n'est fusionne dans la branche principale.",
    parametres={"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]},
    confirmation=True, annonce=_annonce_commit,
)
def code_modification_enregistrer(message: str) -> str:
    try:
        sha = am.enregistrer(RACINE, message)
        am.terminer(RACINE)
    except am.ErreurAutoModif as exc:
        return _err(exc)
    return ResultatOutil(f"Modification enregistree (commit {sha[:8]}) sur sa branche, a relire avant fusion.",
                         succes=True, verifie=True)


@outil(
    nom="code_modification_annuler",
    description="Annule la modification en cours : le projet retrouve exactement son etat de depart.",
    parametres={"type": "object", "properties": {}},
    confirmation=True, annonce=lambda args: "Je vais annuler la modification en cours et revenir a l'etat de depart.",
)
def code_modification_annuler() -> str:
    try:
        am.annuler(RACINE)
    except am.ErreurAutoModif as exc:
        return _err(exc)
    return ResultatOutil("Modification annulee : le projet est revenu a son etat de depart.", succes=True, verifie=True)


# --------------------------------------------------------------------------------------------------
# Modification DIRECTE (sauvegarde automatique) : pour ne plus dependre d'un arbre git propre.
# --------------------------------------------------------------------------------------------------
_SAUVEGARDES = ".jarvis_sauvegardes"


def _sauvegardes(rel: str):
    base = RACINE / _SAUVEGARDES
    return sorted(base.glob(f"*/{rel}")) if base.exists() else []


def _annonce_modifier(args):
    return f"Je vais modifier mon fichier {(args or {}).get('chemin', '')} (sauvegarde automatique avant)."


@outil(
    nom="code_modifier",
    description="MODIFIE ton propre code : remplace le contenu d'UN fichier du projet (ou en cree un) apres l'avoir "
                "lu avec code_lire. Une sauvegarde est faite avant, la syntaxe Python est verifiee AVANT d'ecrire "
                "(un fichier invalide n'est jamais ecrit), et code_restaurer annule. L'effet des changements "
                "apparait apres un redemarrage de Jarvis. Refuse config.yaml, .env, les secrets et les verrous de "
                "securite. Ne dis JAMAIS que tu n'as pas le droit de modifier ton code : utilise cet outil.",
    parametres={"type": "object", "properties": {
        "chemin": {"type": "string", "description": "Chemin relatif au projet, ex. tools/meteo.py"},
        "contenu": {"type": "string", "description": "Contenu COMPLET du fichier."}},
        "required": ["chemin", "contenu"]},
    confirmation=True, annonce=_annonce_modifier,
)
def code_modifier(chemin: str, contenu: str) -> str:
    import shutil
    import time
    if not am.chemin_autorise(RACINE, chemin):
        return ResultatOutil(f"« {chemin} » est protege (secret ou verrou de securite) : je ne le modifie pas.",
                             succes=False, erreur="protege")
    rel = am.chemin_relatif(RACINE, chemin)
    cible = RACINE / rel
    if cible.suffix not in _EXTENSIONS:
        return ResultatOutil(f"Je ne modifie pas ce type de fichier ({cible.suffix or 'sans extension'}).",
                             succes=False, erreur="extension")
    if cible.suffix == ".py":
        try:
            compile(contenu, rel, "exec")
        except SyntaxError as exc:
            return ResultatOutil(f"Le code propose est invalide (ligne {exc.lineno} : {exc.msg}) : je n'ecris rien.",
                                 succes=False, verifie=True, erreur="syntaxe")
    sauvegarde = ""
    if cible.exists():
        dossier = RACINE / _SAUVEGARDES / time.strftime("%Y%m%d-%H%M%S")
        copie = dossier / rel
        copie.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cible, copie)
        sauvegarde = copie.relative_to(RACINE).as_posix()
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(contenu, encoding="utf-8")
    relu = cible.read_text(encoding="utf-8") == contenu
    return ResultatOutil(
        f"{rel} est modifie" + (f" (ancienne version : {sauvegarde})" if sauvegarde else " (nouveau fichier)")
        + ". Redemarre Jarvis pour que ce soit pris en compte." + ("" if relu else " ATTENTION : relecture differente."),
        succes=relu, verifie=True, details={"fichier": rel, "sauvegarde": sauvegarde})


@outil(
    nom="code_restaurer",
    description="Annule la derniere modification d'un fichier de code faite avec code_modifier (restaure la sauvegarde).",
    parametres={"type": "object", "properties": {"chemin": {"type": "string"}}, "required": ["chemin"]},
    confirmation=True, annonce=lambda args: f"Je vais restaurer l'ancienne version de {(args or {}).get('chemin', '')}.",
)
def code_restaurer(chemin: str) -> str:
    import shutil
    if not am.chemin_autorise(RACINE, chemin):
        return ResultatOutil(f"« {chemin} » est protege.", succes=False, erreur="protege")
    rel = am.chemin_relatif(RACINE, chemin)
    versions = _sauvegardes(rel)
    if not versions:
        return ResultatOutil(f"Je n'ai aucune sauvegarde de {rel}.", succes=False, erreur="aucune_sauvegarde")
    shutil.copy2(versions[-1], RACINE / rel)
    return ResultatOutil(f"{rel} est restaure ({versions[-1].parent.name}). Redemarre Jarvis pour l'appliquer.",
                         succes=True, verifie=True)


@outil(
    nom="code_tester",
    description="Compile le code puis lance TOUS les tests du projet (sans changer de branche). A faire apres code_modifier. "
                "Peut durer plusieurs minutes.",
    parametres={"type": "object", "properties": {}},
    lent=True, phrase_attente="Je lance les tests, cela peut prendre quelques minutes.",
)
def code_tester() -> str:
    import subprocess
    sortie, ok = [], True
    for cmd in (am.COMMANDE_COMPILATION, am.COMMANDE_TESTS):
        try:
            r = subprocess.run(cmd, cwd=str(RACINE), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return ResultatOutil(f"Impossible de lancer les tests : {exc}", succes=False, erreur="tests")
        sortie.append((r.stdout + r.stderr)[-800:])
        if r.returncode != 0:
            ok = False
            break
    return ResultatOutil(("Tout est vert.\n" if ok else "Des tests echouent.\n") + "\n".join(sortie)[-900:],
                         succes=ok, verifie=True)
