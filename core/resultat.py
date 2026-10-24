"""Resultat structure d'un outil (S8 du plan de correction).

``ResultatOutil`` est une chaine (``str``) : tout le code existant qui compare,
concatene ou lit le retour d'un outil continue de fonctionner a l'identique.
Elle porte en plus quatre champs que l'orchestration peut lire sans parser du
texte :

- ``succes``   : l'action demandee a-t-elle reellement abouti ?
- ``verifie``  : le resultat a-t-il ete CONSTATE (fenetre au premier plan,
                 texte relu...) et pas seulement suppose ?
- ``details``  : dictionnaire libre (hwnd, titre, executable, ...).
- ``erreur``   : code court de l'echec (« introuvable », « focus », ...).

Regle de fond : un succes non verifie doit le dire (``verifie=False``) et le
message lu a voix haute ne doit jamais affirmer plus que ce qui a ete constate.
"""
from __future__ import annotations


class ResultatOutil(str):
    """str enrichie : message vocal + succes / verification / details / erreur."""

    succes: bool
    verifie: bool
    details: dict
    erreur: str

    def __new__(cls, message, succes=True, verifie=False, details=None, erreur=""):
        obj = super().__new__(cls, str(message))
        obj.succes = bool(succes)
        obj.verifie = bool(verifie)
        obj.details = dict(details or {})
        obj.erreur = str(erreur or "")
        return obj

    def en_dict(self) -> dict:
        return {"message": str(self), "succes": self.succes, "verifie": self.verifie,
                "details": dict(self.details), "erreur": self.erreur}


_DEBUTS_ECHEC = (
    "je ne trouve pas", "je ne vois pas", "je n'ai pas pu", "je n'arrive pas",
    "impossible", "je ne connais pas", "je n'ai pas reussi", "je n'ai pas réussi",
    "je ne tape pas", "je ne clique pas", "desole", "désolé", "erreur",
    # messages d'echec historiques de tools/souris.py (clic a l'ecran, utilise par Astra)
    "ces coordonnees", "bouton inconnu", "le clic a echoue", "je n'ai pas de capture",
)


def est_echec(resultat) -> bool:
    """Vrai si un retour d'outil signale un echec.

    Un ``ResultatOutil`` fait foi. Pour un outil historique qui renvoie du texte
    brut, on se rabat sur ses formules d'echec habituelles (prudent : en cas de
    doute on considere que ce n'est PAS un echec, pour ne pas bloquer a tort).
    """
    if isinstance(resultat, ResultatOutil):
        return not resultat.succes
    texte = str(resultat or "").strip().lower()
    return texte.startswith(_DEBUTS_ECHEC)
