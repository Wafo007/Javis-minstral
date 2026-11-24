"""Modele de donnees de l'audit : statuts de validation explicites, gravites, resultats (findings) et preuves minimales.

Regle centrale : un resultat n'est JAMAIS « CONFIRME » sans preuve technique reproductible ; l'etat initial est POTENTIEL ou
A_VERIFIER. Un LLM ne peut pas changer un statut : seul l'agent de validation le fait, d'apres des regles deterministes.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from enum import Enum


class Statut(str, Enum):
    POTENTIEL = "POTENTIEL"
    A_VERIFIER = "À VÉRIFIER"
    REPRODUIT = "REPRODUIT"
    CONFIRME = "CONFIRMÉ"
    NON_CONCLUANT = "NON CONCLUANT"
    FAUX_POSITIF = "FAUX POSITIF PROBABLE"


class Gravite(str, Enum):
    INFO = "INFO"
    FAIBLE = "FAIBLE"
    MOYENNE = "MOYENNE"
    ELEVEE = "ÉLEVÉE"
    CRITIQUE = "CRITIQUE"


ORDRE_GRAVITE = {Gravite.INFO: 0, Gravite.FAIBLE: 1, Gravite.MOYENNE: 2, Gravite.ELEVEE: 3, Gravite.CRITIQUE: 4}
STATUTS_RETENUS = {Statut.REPRODUIT, Statut.CONFIRME}          # ceux qui comptent comme « vulnerabilites averees »


@dataclass
class Preuve:
    """Preuve technique MINIMALE : jamais de corps de reponse complet ni de donnees personnelles."""
    requete: str = ""          # ex. « GET /ftp »
    statut_http: int | None = None
    extrait: str = ""          # <= 300 caracteres, secrets masques
    observations: list = field(default_factory=list)


@dataclass
class Resultat:
    categorie: str
    titre: str
    description: str
    gravite: Gravite
    composant: str
    ressource: str
    methode: str                       # comment c'est detecte : « analyse des en-tetes HTTP », « gitleaks 8.30.1 »...
    agent: str
    confiance: float = 0.5             # 0..1, fixee par la methode, pas par un LLM
    impact: str = ""
    recommandation: str = ""
    references: list = field(default_factory=list)      # CWE / CVE
    statut: Statut = Statut.POTENTIEL
    preuves: list = field(default_factory=list)
    cle_validation: str = ""           # identifie la regle de reverification (agent de validation)
    donnees: dict = field(default_factory=dict)        # parametres de reverification (url, parametre...)
    horodatage: float = field(default_factory=time.time)
    id: str = ""
    historique_statut: list = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            base = f"{self.categorie}|{self.ressource}|{self.composant}|{self.titre}"
            self.id = "JSI-" + hashlib.sha1(base.encode("utf-8")).hexdigest()[:8].upper()

    def changer_statut(self, nouveau: Statut, motif: str):
        self.historique_statut.append({"de": self.statut.value, "vers": nouveau.value, "motif": motif[:200], "t": time.time()})
        self.statut = nouveau

    def vers_dict(self) -> dict:
        d = asdict(self)
        d["gravite"], d["statut"] = self.gravite.value, self.statut.value
        return d

    @staticmethod
    def depuis_dict(d: dict) -> "Resultat":
        d = dict(d)
        d["gravite"], d["statut"] = Gravite(d["gravite"]), Statut(d["statut"])
        d["preuves"] = [Preuve(**p) if isinstance(p, dict) else p for p in d.get("preuves", [])]
        return Resultat(**d)


def masquer(texte: str, maxi: int = 300) -> str:
    """Masque les secrets evidents dans un extrait de preuve, puis tronque."""
    import re
    t = str(texte or "")
    t = re.sub(r"(?i)(authorization|cookie|set-cookie|token|secret|password|passwd|api[_-]?key)(\"?\s*[:=]\s*\"?)([^\s\"';,&]{4,})",
               lambda m: m.group(1) + m.group(2) + m.group(3)[:2] + "…[masqué]", t)
    t = re.sub(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}", "eyJ…[JWT masqué]", t)
    t = re.sub(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", lambda m: m.group(0)[0] + "***@***", t)   # emails : donnees personnelles
    t = re.sub(r"\b[A-Fa-f0-9]{32,}\b", lambda m: m.group(0)[:6] + "…[hex masqué]", t)
    return t[:maxi]
