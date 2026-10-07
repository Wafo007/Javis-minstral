"""Routage vocal déterministe des lectures multimédias courantes.

Ces commandes sont locales, réversibles et étroitement bornées. Elles évitent
donc de confier à Astra une simple pause, un changement de piste ou la recherche
d'un contenu Spotify/Netflix.
"""
import re
import time
from urllib.parse import quote_plus

from core.registre import outil
from core.util import sans_accents


_VERBES_LECTURE = {
    "mets", "met", "lance", "lancer", "joue", "jouer", "ecoute", "ecouter",
    "demarre", "demarrer",
}
_PREFIXES = (
    ("hey", "jarvis"), ("jarvis",),
    ("est", "ce", "que", "tu", "peux"),
    ("est", "ce", "que", "tu", "pourrais"),
    ("peux", "tu"), ("tu", "peux"),
    ("pourrais", "tu"), ("tu", "pourrais"),
    ("je", "veux", "que", "tu"),
    ("je", "voudrais", "que", "tu"),
    ("j", "aimerais", "que", "tu"),
    ("vas", "y"), ("allez",),
    ("s", "il", "te", "plait"), ("stp",),
)
_SUFFIXES_POLITES = (
    ("s", "il", "te", "plait"), ("stp",), ("merci",), ("jarvis",),
    ("maintenant",),
)


def _mots(phrase):
    mots = re.sub(r"[^a-z0-9]+", " ", sans_accents(str(phrase or ""))).split()
    change = True
    while mots and change:
        change = False
        for prefixe in _PREFIXES:
            if tuple(mots[:len(prefixe)]) == prefixe:
                del mots[:len(prefixe)]
                change = True
                break
    change = True
    while mots and change:
        change = False
        for suffixe in _SUFFIXES_POLITES:
            if tuple(mots[-len(suffixe):]) == suffixe:
                del mots[-len(suffixe):]
                change = True
                break
    return mots


def _retirer_service(mots, service):
    sortie = list(mots)
    for prefixe in (("sur", service), ("dans", service), ("avec", service)):
        if tuple(sortie[-len(prefixe):]) == prefixe:
            del sortie[-len(prefixe):]
            break
    if sortie and sortie[0] == service:
        del sortie[0]
    return sortie


def _commande_transport(mots):
    """Action média explicite, avec variantes naturelles et nom du service."""
    mots = list(mots)
    while mots and mots[0] in {"m", "me", "moi"}:
        del mots[0]
    texte = " ".join(mots)
    ensemble = set(mots)
    # « Ne mets pas en pause » ne doit surtout pas produire l'action inverse.
    if re.search(r"\b(?:ne|n)\b.*\bpas\b", texte):
        return None
    if texte in {"suivant", "suivante", "next", "skip"} or any(
            formulation in texte for formulation in (
            "change de musique", "musique suivante", "piste suivante",
            "chanson suivante", "passe a la suivante",
            "passe au morceau suivant", "morceau suivant",
            "mets la suivante", "mets le suivant", "passe a la suite",
            "saute ce morceau", "skip ce morceau", "change de chanson",
            "avance d un morceau", "prochaine chanson", "prochain morceau")):
        return "suivant"
    if texte in {"precedent", "precedente"} or any(
            formulation in texte for formulation in (
            "musique precedente", "piste precedente", "chanson precedente",
            "reviens a la precedente", "passe a la precedente",
            "morceau precedent", "mets la precedente", "mets le precedent",
            "remets celle d avant", "remets celui d avant",
            "chanson d avant", "morceau d avant", "reviens d un morceau")):
        return "precedent"

    pause_exacte = {
        "pause", "stop", "arrete", "mets pause", "met pause",
        "mets en pause", "met en pause", "mets sur pause", "met sur pause",
        "fais pause", "fais une pause", "appuie sur pause",
        "appuies sur pause", "passe en pause", "pause la musique",
        "pause spotify", "stop la musique", "stop spotify",
        "fais stop", "mets stop", "met stop",
    }
    verbes_pause = {
        "pause", "arrete", "stop", "stoppe", "coupe", "suspends", "suspend",
        "interromps", "interrompt", "eteins", "eteint", "arreter",
        "stopper", "couper", "suspendre", "interrompre", "eteindre",
        "arretes", "stoppes", "coupes", "interrompes", "eteignes",
    }
    cibles_media = {
        "musique", "spotify", "lecture", "son", "audio", "morceau",
        "chanson", "titre", "playlist", "ca", "joue", "ecoute", "ecoutais",
    }
    if (texte in pause_exacte
            or (mots and mots[0] in verbes_pause
                and (len(mots) == 1 or bool(ensemble & cibles_media)))
            or ("pause" in ensemble and mots and mots[0] in {
                "mets", "met", "mettre", "fais", "fait", "appuie",
                "appuies", "passe", "active", "bloque",
            })
            or any(formulation in texte for formulation in (
                "arrete de jouer", "arrete ce qui joue", "ne joue plus",
                "fais taire la musique", "fais arreter la musique",
                "je ne veux plus de musique"))):
        return "pause"

    reprise_exacte = {
        "play", "lecture", "reprends", "reprend", "continue", "relance",
        "remets", "remet", "repars", "mets play", "met play",
        "fais play", "appuie sur play", "appuies sur play",
        "mets en lecture", "met en lecture", "passe en lecture",
        "enleve la pause", "retire la pause", "desactive la pause",
        "sors de pause", "remets le son", "remet le son",
    }
    verbes_reprise = {
        "reprends", "reprend", "remets", "remet", "relance", "continue",
        "redemarre", "repars", "recommence", "reprendre", "remettre",
        "relancer", "continuer", "redemarrer", "repartir", "recommencer",
        "rallume", "rallumer", "reactive", "reactiver",
        "reprennes", "relances", "continues", "redemarres", "rallumes",
        "reactives",
    }
    verbes_lecture_simple = {
        "mets", "met", "joue", "lance", "demarre", "mettre", "jouer",
        "lancer", "demarrer", "joues", "lances", "demarres",
    }
    mots_liaison = {
        "la", "le", "l", "du", "de", "en", "sur", "moi", "ma", "mon",
    }
    reste_simple = ensemble - mots_liaison - verbes_lecture_simple
    if (texte in reprise_exacte
            or (mots and mots[0] in verbes_reprise
                and (len(mots) == 1 or bool(ensemble & cibles_media)
                     or any(expression in texte for expression in (
                         "la ou tu t es arrete", "la ou ca s est arrete",
                         "ou tu en etais", "ce qui jouait"))))
            or (mots and mots[0] in verbes_lecture_simple
                and reste_simple
                and reste_simple <= {"musique", "spotify", "lecture", "son", "audio"})
            or any(formulation in texte for formulation in (
                "fais repartir la musique", "fais repartir spotify",
                "fais reprendre la musique", "fais relancer la musique",
                "reprends la ou tu t es arrete", "continue la ou tu en etais",
                "reprends la ou on en etait", "continue la ou on en etait",
                "remets ce qui jouait", "relance ce qui jouait",
                "reprends ce que j ecoutais", "remets ce que j ecoutais",
                "continue ce que j ecoutais"))):
        return "reprendre"
    return None


def router_commande_media(phrase, piece=""):
    """Renvoie ``(outil, arguments)`` pour une commande média non ambiguë."""
    mots = _mots(phrase)
    if not mots or "alexa" in mots or "echo" in mots:
        return None

    action = _commande_transport(mots)
    if action:
        if piece:
            return "controler_spotify", {"action": action, "piece": piece}
        return "controler_media", {
            "action": "pause" if action == "reprendre" else action,
        }

    if mots[0] not in _VERBES_LECTURE:
        return None
    del mots[0]
    if mots and mots[0] in {"m", "me", "moi"}:
        del mots[0]

    if "netflix" in mots:
        mots = _retirer_service(mots, "netflix")
        for prefixe in (("la", "serie"), ("ma", "serie"), ("le", "film"),
                        ("mon", "film"), ("la", "saison"), ("ma", "saison"),
                        ("serie",), ("film",), ("saison",)):
            if tuple(mots[:len(prefixe)]) == prefixe:
                del mots[:len(prefixe)]
                break
        titre = " ".join(mots).strip()
        return ("lire_netflix", {"titre": titre}) if titre else None

    spotify_explicit = "spotify" in mots
    mots = _retirer_service(mots, "spotify")
    type_media = "titre"
    prefixes_playlist = (
        ("ma", "playlist"), ("la", "playlist"), ("une", "playlist"),
        ("playlist",),
    )
    for prefixe in prefixes_playlist:
        if tuple(mots[:len(prefixe)]) == prefixe:
            del mots[:len(prefixe)]
            type_media = "playlist"
            break
    if type_media == "titre":
        for prefixe in (("la", "chanson"), ("le", "morceau"), ("le", "titre"),
                        ("chanson",), ("morceau",), ("titre",)):
            if tuple(mots[:len(prefixe)]) == prefixe:
                del mots[:len(prefixe)]
                spotify_explicit = True
                break
    recherche = " ".join(mots).strip()
    if recherche and (spotify_explicit or type_media == "playlist"):
        args = {"recherche": recherche, "type_media": type_media}
        if piece:
            args["piece"] = piece
        return "lire_spotify", args
    return None


@outil(
    nom="lire_netflix",
    description="Recherche et lance une série ou un film précis sur Netflix sans "
                "prendre le contrôle général du PC. Pour « lance la série X sur "
                "Netflix » ou « mets le film Y sur Netflix ».",
    parametres={
        "type": "object",
        "properties": {
            "titre": {"type": "string", "description": "Titre de la série ou du film."},
        },
        "required": ["titre"],
    },
    lent=True,
    phrase_attente="J'ouvre le titre sur Netflix.",
)
def lire_netflix(titre: str) -> str:
    """Ouvre la recherche Netflix puis tente une seule action de lecture sûre."""
    titre = str(titre or "").strip()
    if not titre:
        return "Dis-moi quelle série ou quel film lancer sur Netflix."
    from tools.navigateur import browser_interact, browser_open
    ouverture = browser_open(
        url=f"https://www.netflix.com/search?q={quote_plus(titre)}")
    if "pas pu" in ouverture.lower() or "reussi" in ouverture.lower():
        return ouverture
    time.sleep(1.0)
    action = browser_interact(
        f"Sur Netflix uniquement, lance le résultat correspondant exactement à « {titre} » "
        "en cliquant sur son bouton Lecture s'il est visible ; sinon ouvre sa fiche. "
        "Ne choisis rien si la correspondance n'est pas claire.")
    if action.startswith(("C'est", "Saisi", "Voila")):
        return f"Je lance « {titre} » sur Netflix."
    return f"J'ai ouvert la recherche Netflix pour « {titre} »."
