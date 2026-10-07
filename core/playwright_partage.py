"""Instance Playwright partagee (une seule pour tout le process).

Les outils reservation (navigateur pilote) et navigateur (connexion a Chrome)
utilisent Playwright dans le meme thread ; on ne demarre qu'une instance pour
eviter tout conflit de boucle interne.
"""
_PW = None


def obtenir():
    global _PW
    if _PW is None:
        from playwright.sync_api import sync_playwright
        _PW = sync_playwright().start()
    return _PW
