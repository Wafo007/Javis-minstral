"""Instance Playwright partagee (une seule pour tout le process).

Les outils reservation (navigateur pilote) et navigateur (connexion a Chrome)
utilisent Playwright dans le meme thread ; on ne demarre qu'une instance pour
eviter tout conflit de boucle interne.

Deux pieges reels que ce module rend explicites (S3 du plan de correction) :

1. « import playwright » ne prouve RIEN : le chargement de l'API synchrone (greenlet, DLL native
   _greenlet) ou le demarrage du moteur peuvent echouer alors que l'import du paquet reussit.
   ``diagnostiquer()`` execute la chaine complete et dit a quelle etape elle casse.
2. L'API synchrone repose sur des greenlets lies au thread qui a demarre Playwright : l'appeler
   depuis un autre thread leve une erreur obscure. ``obtenir()`` la remplace par un message clair.
"""
from __future__ import annotations

import logging
import threading

LOG = logging.getLogger("jarvis.playwright")

_PW = None
_FIL = None            # identifiant du thread qui a demarre l'instance


class PlaywrightIndisponible(RuntimeError):
    """Playwright ne peut pas etre utilise ; le message est destine a etre lu a l'utilisateur."""


def expliquer_erreur(exc) -> str:
    """Traduit une exception Playwright/greenlet en cause probable + remede (texte court)."""
    texte = f"{type(exc).__name__}: {exc}"
    bas = texte.lower()
    if "_greenlet" in bas or "greenlet" in bas or "dll load failed" in bas:
        return ("Le moteur Playwright (greenlet) ne se charge pas sur ce PC : installe le "
                "redistribuable Microsoft Visual C++ 2015-2022 puis lance "
                "« uv sync --reinstall-package greenlet --reinstall-package playwright ».")
    if "no module named" in bas and "playwright" in bas:
        return "Le module Playwright est absent. Lance : uv sync, puis relance Jarvis."
    if "executable doesn't exist" in bas or "playwright install" in bas:
        return "Le navigateur de Playwright n'est pas installe. Lance : uv run playwright install chromium."
    if "different thread" in bas or "cannot switch" in bas:
        return "Playwright a ete appele depuis un autre thread que celui qui l'a demarre."
    return texte[:200]


def obtenir():
    """Instance Playwright partagee (demarree au premier appel, dans le thread appelant)."""
    global _PW, _FIL
    courant = threading.get_ident()
    if _PW is not None:
        if _FIL != courant:
            raise PlaywrightIndisponible(
                "Playwright (API synchrone) est lie a un autre thread : l'action navigateur doit "
                "etre lancee depuis le thread qui l'a demarre.")
        return _PW
    try:
        from playwright.sync_api import sync_playwright
        _PW = sync_playwright().start()
    except Exception as exc:
        _PW = None
        LOG.warning("Playwright ne demarre pas : %s", expliquer_erreur(exc))
        raise
    _FIL = courant
    return _PW


def arreter():
    """Arrete et oublie l'instance (apres une perte de connexion, avant un nouvel essai)."""
    global _PW, _FIL
    pw, _PW, _FIL = _PW, None, None
    if pw is not None:
        try:
            pw.stop()
        except Exception:
            LOG.debug("arret de Playwright", exc_info=True)


def diagnostiquer(lancer_navigateur=True) -> list[tuple[str, bool, str]]:
    """Chaine COMPLETE, etape par etape : [(etape, ok, detail)]. S'arrete a la premiere etape en echec.

    Utilise une instance temporaire (dans un thread dedie : l'API synchrone est interdite dans une
    boucle asyncio deja active) ; l'instance partagee n'est pas touchee.
    """
    etapes: list[tuple[str, bool, str]] = []

    def noter(nom, ok, detail=""):
        etapes.append((nom, ok, detail))
        return ok

    def travail():
        try:
            import playwright  # noqa: F401
            noter("import playwright", True, getattr(playwright, "__version__", ""))
        except Exception as exc:
            noter("import playwright", False, expliquer_erreur(exc))
            return
        try:
            import greenlet
            noter("import greenlet", True, getattr(greenlet, "__version__", ""))
            from playwright.sync_api import sync_playwright
            noter("playwright.sync_api", True)
        except Exception as exc:
            noter("chargement reel (sync_api / _greenlet)", False, expliquer_erreur(exc) + " | ERREUR BRUTE : " + f"{type(exc).__name__}: {exc}"[:400])
            return
        try:
            pw = sync_playwright().start()
        except Exception as exc:
            noter("demarrage du moteur", False, expliquer_erreur(exc))
            return
        try:
            noter("demarrage du moteur", True)
            if not lancer_navigateur:
                return
            try:
                exe = pw.chromium.executable_path
                noter("chromium installe", bool(exe), str(exe))
                navigateur = pw.chromium.launch(headless=True)
                page = navigateur.new_page()
                page.set_content("<title>jarvis</title><p>ok</p>")
                noter("lancement + page", page.title() == "jarvis", "chromium headless")
                navigateur.close()
            except Exception as exc:
                noter("lancement de chromium", False, expliquer_erreur(exc))
        finally:
            try:
                pw.stop()
            except Exception:
                pass

    fil = threading.Thread(target=travail, name="diag-playwright", daemon=True)
    fil.start()
    fil.join(90)
    if fil.is_alive():
        noter("delai", False, "le diagnostic Playwright n'a pas repondu en 90 s")
    return etapes
