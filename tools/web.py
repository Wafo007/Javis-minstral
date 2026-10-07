"""Outil de recherche web (DuckDuckGo)."""
from core.registre import outil


@outil(
    nom="chercher_web",
    description="Cherche une information actuelle sur le web. A utiliser pour "
                "l'actualite, la meteo, les faits recents ou tout ce que tu ignores.",
    parametres={
        "type": "object",
        "properties": {"requete": {"type": "string", "description": "La recherche"}},
        "required": ["requete"],
    },
    lent=True,
    phrase_attente="Je cherche ca tout de suite.",
)
def chercher_web(requete: str) -> str:
    """Cherche sur le web et renvoie un resume des premiers resultats."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "La recherche web n'est pas installee."

    try:
        with DDGS() as ddgs:
            resultats = list(ddgs.text(requete, region="fr-fr", max_results=3))
        if not resultats:
            return "Aucun resultat."
        return " ".join(r.get("body", "")[:300] for r in resultats)
    except Exception as e:
        return f"Recherche impossible : {e}"
