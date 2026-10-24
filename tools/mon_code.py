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
_EXTENSIONS = {".py", ".md", ".txt", ".yaml", ".yml", ".json", ".html", ".toml", ".bat", ".ps1"}
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
