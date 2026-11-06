"""Dialogues specialises (deterministes, sans LLM, sans Internet) avec rotation anti-repetition."""
from __future__ import annotations

import random

ACTIVATION = [
    "Initialisation du protocole Ghost. Environnement tactique activé. Commandant, je suis opérationnel.",
    "Protocole Ghost en ligne. Tous les systèmes tactiques sont prêts, Commandant.",
    "Ghost Protocol initialisé. L'environnement est sécurisé. J'attends vos ordres, Commandant.",
]
DEJA_ACTIF = [
    "Le protocole Ghost est déjà actif, Commandant.",
    "Déjà en mode Ghost. Rien à réinitialiser.",
]
DESACTIVATION = [
    "Fermeture du protocole Ghost. Retour à l'environnement standard. Ce fut un plaisir, Commandant.",
    "Protocole Ghost désactivé. Je reprends mon comportement habituel.",
    "Sortie du mode tactique. Systèmes normaux rétablis.",
]
INACTIF = [
    "Le mode Ghost n'est pas actif. Dis « active le mode hacker » pour l'entrer.",
]
DEJA_EN_COURS = [
    "Une simulation est déjà en cours, Commandant. Laissez-la se terminer, ou dites « arrête la simulation ».",
]
DEBUT = {
    "recon": ["Ghost Recon engagé. Analyse tactique en cours.", "Reconnaissance lancée. Je vous prépare le rapport."],
    "intelligence": ["Moteur d'intelligence initialisé. Analyse complète en cours.", "Analyse complète lancée, Commandant."],
    "attack": ["Simulation d'intrusion en préparation. Aucun accès réel, uniquement un environnement virtuel.",
               "Scénario Ghost Attack généré. Tout reste local et fictif."],
}
FIN = {
    "recon": ["Reconnaissance terminée. Rapport affiché, résultats simulés signalés comme tels.",
              "J'ai terminé l'analyse de votre scénario. Les éléments réels et simulés sont distingués."],
    "intelligence": ["Simulation terminée. Tous les systèmes sont opérationnels.",
                     "Analyse complète terminée. Évaluation de menace fictive disponible à l'écran."],
    "attack": ["Simulation d'intrusion terminée. Accès appareil : aucun. Accès réseau : aucun.",
               "Ghost Attack terminé. Environnement virtuel uniquement, aucun système réel touché."],
}
ARRET = ["Simulation interrompue. Aucun système n'a été touché.", "Simulation arrêtée, Commandant."]
AUCUNE = ["Aucune simulation en cours."]
VOIX_COUPEE = ["Voix Ghost coupée : la voix Windows prend le relais. Je ne consomme plus de quota."]
VOIX_RETABLIE = ["Voix Ghost rétablie."]
ANOMALIE = "Une anomalie virtuelle vient d'être détectée."


class Repertoire:
    """Choisit une phrase du pool sans repeter la precedente."""

    def __init__(self, hasard=None):
        self._h = hasard or random.Random()
        self._dernier = {}

    def choisir(self, nom, pool):
        choix = [p for p in pool if p != self._dernier.get(nom)] or list(pool)
        phrase = self._h.choice(choix)
        self._dernier[nom] = phrase
        return phrase
