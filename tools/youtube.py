"""Lire une video YouTube SANS clic ni Playwright.

Journal reel : « va sur YouTube, lance Stromae, clique sur la premiere video » echouait en boucle,
parce que cliquer a l'aveugle sur une page de resultats depend de la vision (coordonnees devinees) et de
Playwright (casse sur ce PC). Ici on lit la page de resultats, on prend l'identifiant de la premiere video
et on ouvre directement sa page de lecture : plus aucun clic a deviner.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

from core.registre import outil
from core.resultat import ResultatOutil

LOG = logging.getLogger("jarvis.youtube")
_RESULTATS = "https://www.youtube.com/results?search_query="
_ENTETES = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
    "Cookie": "CONSENT=YES+1; SOCS=CAI",       # evite la page de consentement europeenne
}


def extraire_videos(html: str) -> list[tuple[str, str]]:
    """[(identifiant, titre)] dans l'ordre d'affichage, depuis la page de resultats YouTube."""
    m = re.search(r"ytInitialData\s*=\s*(\{.*?\})\s*;\s*</script>", html or "", re.S)
    trouves: list[tuple[str, str]] = []
    if m:
        try:
            donnees = json.loads(m.group(1))
        except ValueError:
            donnees = None

        def parcourir(noeud):
            if isinstance(noeud, dict):
                v = noeud.get("videoRenderer")
                if isinstance(v, dict) and re.fullmatch(r"[\w-]{11}", str(v.get("videoId", ""))):
                    runs = (v.get("title") or {}).get("runs") or [{}]
                    trouves.append((v["videoId"], str(runs[0].get("text", ""))))
                for x in noeud.values():
                    parcourir(x)
            elif isinstance(noeud, list):
                for x in noeud:
                    parcourir(x)

        if donnees is not None:
            parcourir(donnees)
    if not trouves:            # repli : premiers identifiants de video du HTML brut
        for vid in re.findall(r'"videoId":"([\w-]{11})"', html or ""):
            if vid not in [t[0] for t in trouves]:
                trouves.append((vid, ""))
    vus, uniques = set(), []
    for vid, titre in trouves:
        if vid not in vus:
            vus.add(vid)
            uniques.append((vid, titre))
    return uniques


def _telecharger(requete: str) -> str:
    req = urllib.request.Request(_RESULTATS + urllib.parse.quote_plus(requete), headers=_ENTETES)
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", "replace")


def _ouvrir(url: str) -> bool:
    from core.ouvrir_web import ouvrir_url
    return bool(ouvrir_url(url))


@outil(
    nom="youtube_lire",
    description="LANCE une video YouTube : « lance/joue/mets Stromae sur YouTube », « lance la premiere video de "
                "X ». Trouve la video et l'ouvre directement, sans cliquer. A utiliser a la place de "
                "browser_open + clics des qu'on veut LIRE une video (rang=1 : la premiere, 2 : la deuxieme...).",
    parametres={"type": "object", "properties": {
        "requete": {"type": "string", "description": "Ce qu'il faut chercher (titre, artiste)."},
        "rang": {"type": "integer", "description": "1 = premiere video (defaut)."}},
        "required": ["requete"]},
)
def youtube_lire(requete: str, rang: int = 1) -> str:
    requete = " ".join(str(requete or "").split())
    if not requete:
        return ResultatOutil("Dis-moi quelle video lancer.", succes=False, erreur="vide")
    rang = max(1, int(rang or 1))
    resultats_url = _RESULTATS + urllib.parse.quote_plus(requete)
    try:
        videos = extraire_videos(_telecharger(requete))
    except Exception as exc:
        LOG.warning("youtube_lire : lecture des resultats impossible : %s", exc)
        videos = []
    if len(videos) < rang:
        ouvert = _ouvrir(resultats_url)
        return ResultatOutil(
            "Je n'ai pas pu identifier la video : j'ai ouvert la page de resultats, il faudra choisir." if ouvert
            else f"Je n'ai pas pu lancer la video. Les resultats : {resultats_url}",
            succes=False, verifie=False, erreur="introuvable")
    vid, titre = videos[rang - 1]
    if not _ouvrir(f"https://www.youtube.com/watch?v={vid}"):
        return ResultatOutil("J'ai trouve la video mais je n'ai pas pu ouvrir le navigateur.",
                             succes=False, erreur="navigateur")
    return ResultatOutil(f"Je lance la video{(' « ' + titre + ' »') if titre else ''} sur YouTube.",
                         succes=True, verifie=False, details={"video": vid, "titre": titre})


_VERBES = r"(?:recherche|cherche|lance|joue|mets|met|regarde|ecoute|passe)"
_ARTICLE = r"^(?:(?:la|le|une|un|l)\s+)?(?:(?:premiere|1ere|1re)\s+)?(?:(?:video|clip|musique|chanson|titre)\s+)?(?:(?:de|du|des|d)\s+)?"
_VIDES = {"", "youtube", "ca", "cela", "ici", "la", "dessus", "video", "videos", "musique", "le", "une", "un",
          "mon navigateur", "navigateur"}


def router_youtube(phrase, piece=""):
    """« lance Stromae sur YouTube » -> ('youtube_lire', {...}). None si la demande n'est pas une lecture."""
    from core.util import sans_accents
    s = sans_accents(str(phrase or "")).lower()
    if "youtube" not in s:
        return None
    for m in re.finditer(r"\b" + _VERBES + r"\s+(.+?)(?=\s+sur youtube\b|\s+et\s+(?:lance|joue|mets|clique)\b|"
                         r"\s+puis\b|[.!?]|$)", s):
        q = re.sub(_ARTICLE, "", m.group(1).strip()).strip(" ,;:-")
        q = re.sub(r"\s*(?:sur youtube|sur le navigateur)$", "", q).strip(" ,;:-")
        if q in _VIDES or " que tu " in f" {q} " or q.startswith(("que ", "ce ", "cette ")) or len(q) < 2:
            continue
        if re.match(r"youtube\b", q):
            continue
        # le texte d'origine (accents) est conserve quand les longueurs concordent
        debut = s.find(q)
        original = str(phrase)
        if len(original) == len(s) and debut >= 0:
            q = original[debut:debut + len(q)]
        return "youtube_lire", {"requete": q}
    return None
