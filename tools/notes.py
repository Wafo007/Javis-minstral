"""Notes de Jarvis : tes idees de contenu, courses, taches... en markdown.

Chaque categorie est un fichier de notes/ (idees.md, courses.md, taches.md...).
Une note = une ligne horodatee avec sa source (voix, iPhone...). Le dossier notes/
n'est pas versionne (donnees perso).

Alimente par la voix ("note cette idee...") et par le pont iPhone (core.pont_iphone).
Outils vocaux : sortir_idee (pioche au hasard), notes_du_jour (resume du jour).
"""
import datetime as dt
import logging
import random
from pathlib import Path

from core.registre import outil
from core.util import sans_accents

LOG = logging.getLogger("jarvis")
_RACINE = Path(__file__).resolve().parent.parent

CATEGORIES = {
    "idees": ["idee", "contenu", "video", "reel", "post", "script", "sujet", "concept"],
    "courses": ["acheter", "course", "liste", "magasin", "supermarche", "panier"],
    "taches": ["faire", "tache", "todo", "rappel", "penser a", "ne pas oublier"],
}
DEFAUT = "idees"


def _dossier():
    d = _RACINE / "notes"
    d.mkdir(exist_ok=True)
    return d


def _fichier(categorie):
    cat = sans_accents(categorie or DEFAUT).lower().strip() or DEFAUT
    cat = "".join(c for c in cat if c.isalnum() or c == "_") or DEFAUT
    return _dossier() / f"{cat}.md"


def categoriser(contenu):
    """Choisit une categorie pour une note (categories connues + heuristique)."""
    plat = sans_accents((contenu or "").lower())
    for cat, mots in CATEGORIES.items():
        if any(m in plat for m in mots):
            return cat
    return DEFAUT


def ajouter_note(contenu, categorie=None, source="voix"):
    """Ajoute une note horodatee. Renvoie (categorie, ligne)."""
    contenu = (contenu or "").strip()
    if not contenu:
        return None, ""
    cat = (categorie or "").strip() or categoriser(contenu)
    cat = _fichier(cat).stem
    horo = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    ligne = f"- [{horo}] {contenu} _(via {source})_\n"
    f = _fichier(cat)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(ligne)
    LOG.info("note ajoutee (%s, via %s) : %s", cat, source, contenu[:80])
    return cat, ligne


def _lignes(categorie):
    f = _fichier(categorie)
    if not f.exists():
        return []
    return [l.rstrip("\n") for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def _texte_note(ligne):
    """Extrait le contenu d'une ligne '- [date] contenu _(via x)_'."""
    t = ligne
    if "]" in t:
        t = t.split("]", 1)[1]
    if "_(via" in t:
        t = t.split("_(via", 1)[0]
    return t.strip(" -")


# ------------------------------------------------------------------- outils

@outil(
    nom="sortir_idee",
    description="Pioche AU HASARD une idee de contenu dans tes notes et te la lit. "
                "Pour 'sors-moi une idee', 'donne-moi une idee de contenu', 'sur quoi "
                "je pourrais bosser'.",
    mcp_expose=False,
)
def sortir_idee() -> str:
    lignes = _lignes("idees")
    if not lignes:
        return ("Tu n'as pas encore d'idees notees. Envoie-m'en depuis ton iPhone ou "
                "dis 'note cette idee : ...'.")
    idee = _texte_note(random.choice(lignes))
    return f"Voila une idee a creuser : {idee}"


@outil(
    nom="notes_du_jour",
    description="Resume les notes que tu as prises aujourd'hui (toutes categories). "
                "Pour 'qu'est-ce que j'ai note aujourd'hui', 'mes notes du jour'.",
    mcp_expose=False,
)
def notes_du_jour() -> str:
    auj = dt.datetime.now().strftime("%Y-%m-%d")
    trouve = []
    for f in _dossier().glob("*.md"):
        for ligne in _lignes(f.stem):
            if f"[{auj}" in ligne:
                trouve.append(f"{f.stem} : {_texte_note(ligne)}")
    if not trouve:
        return "Tu n'as rien note aujourd'hui."
    apercu = " ; ".join(trouve[:8])
    return f"Aujourd'hui tu as note {len(trouve)} chose(s) : {apercu}."


@outil(
    nom="noter",
    description="Enregistre une note/idee que l'utilisateur dicte. Pour 'note cette "
                "idee : ...', 'ajoute a mes courses : ...', 'rappelle-moi de ...'. "
                "Choisis la categorie (idees, courses, taches) selon le contenu.",
    parametres={
        "type": "object",
        "properties": {
            "contenu": {"type": "string", "description": "Le texte de la note."},
            "categorie": {"type": "string",
                          "description": "idees, courses, taches... (optionnel, devine sinon)."},
        },
        "required": ["contenu"],
    },
    mcp_expose=False,
)
def noter(contenu: str, categorie: str = "") -> str:
    cat, _ = ajouter_note(contenu, categorie, source="voix")
    if not cat:
        return "Je n'ai rien a noter."
    return f"C'est note dans {cat}."
