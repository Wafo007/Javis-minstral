"""Tests GHOST PROTOCOL.

HONNETETE : ElevenLabs n'est JAMAIS appele pour de vrai ici. Le transport HTTP est un DOUBLE (FauxHTTP) : ces tests
valident NOTRE logique (cache, disjoncteur, repli, comptage, en-tetes), pas le comportement reel de l'API ni une voix reelle.
Le script de demonstration, lui, est execute pour de vrai (sous-processus isole, reseau bloque).
"""
from __future__ import annotations

import ast
import logging
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from modes.ghost_protocol import (commandes, config as cfg, controller, elevenlabs_provider as el, fake_code_generator as fcg,
                                  fake_intelligence as fi, hud_bridge, voice_manager)
from modes.ghost_protocol.audio_cache import CacheAudio
from modes.ghost_protocol.state_manager import ETAT, VOIX_ELEVENLABS, VOIX_FALLBACK

RACINE = Path(__file__).resolve().parent.parent
CLE_FACTICE = "cle-factice-pour-tests-0000"


class FauxHTTP:
    """Double du transport HTTP : file de reponses (statut, corps) ou d'exceptions ErreurVoix."""

    def __init__(self, reponses=None):
        self.reponses = list(reponses or [])
        self.appels = []

    def __call__(self, url, corps, entetes, timeout):
        self.appels.append({"url": url, "corps": corps, "entetes": dict(entetes), "timeout": timeout})
        r = self.reponses.pop(0) if self.reponses else (200, b"AUDIO")
        if isinstance(r, Exception):
            raise r
        return r


def decodeur(octets):
    return np.arange(2400, dtype=np.int16)


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture(autouse=True)
def _isolation(monkeypatch, tmp_path):
    for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(cfg, "_fichier_env", lambda: {})
    monkeypatch.setattr(cfg, "_reglage", lambda chemin, defaut=None: defaut)
    monkeypatch.setattr(cfg, "dossier_donnees", lambda: tmp_path)
    ETAT.remettre_a_zero()
    voice_manager.remplacer_provider(None)
    hud_bridge.JOURNAL.clear()
    yield
    ETAT.remettre_a_zero()
    voice_manager.remplacer_provider(None)


@pytest.fixture
def ctrl(tmp_path):
    return controller.GhostController(vitesse=2000, dossier=tmp_path)


@pytest.fixture
def voix_cfg(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", CLE_FACTICE)
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "voix-test")


def fournisseur(tmp_path, http=None, horloge=None):
    h = horloge or Horloge()
    return el.GhostElevenLabsProvider(http=http or FauxHTTP(), cache=CacheAudio(tmp_path / "c", 10_000_000),
                                      usage=el.UsageVoix(tmp_path / "u.json"), horloge=h, decodeur=decodeur, budget=False), h


def attendre(ctrl, delai=10):
    assert ctrl.moteur.attendre(delai), "simulation trop longue"


# 1-4 ---------------------------------------------------------------------------------------------------------
def test_01_activation(ctrl):
    phrase = commandes.essayer("Jarvis, active le mode hacker", ctrl)
    assert phrase and "Commandant" in phrase or "Ghost" in phrase
    assert ETAT.actif and not ETAT.sortie_en_attente
    assert any(e["t"] == "ghost" and e["actif"] for e in hud_bridge.JOURNAL)
    for dite in ("Active Ghost Protocol", "active le protocole ghost"):
        ETAT.remettre_a_zero()
        assert commandes.essayer(dite, ctrl) and ETAT.actif


def test_02_desactivation_apres_adieu(ctrl):
    ctrl.activer()
    adieu = commandes.essayer("Désactive le mode hacker", ctrl)
    assert adieu
    # l'adieu est encore prononce AVEC la voix Ghost : le mode ne bascule qu'apres
    assert ETAT.actif and ETAT.sortie_en_attente and voice_manager.provider_actif() is not None
    assert ctrl.finaliser_sortie() is True
    assert not ETAT.actif and voice_manager.provider_actif() is None
    ctrl.activer()
    assert commandes.essayer("Quitte Ghost Protocol", ctrl)
    ctrl.finaliser_sortie()
    assert not ETAT.actif


def test_03_activation_repetee(ctrl):
    p1 = ctrl.activer()
    debut = ETAT.depuis
    p2 = ctrl.activer()
    assert ETAT.actif and ETAT.depuis == debut and p2 != "" and p1
    assert sum(1 for e in hud_bridge.JOURNAL if e["t"] == "ghost_term" and "INITIALIZED" in e["texte"]) == 1


def test_04_retour_theme_normal(ctrl):
    ctrl.activer()
    ctrl.lancer_intelligence()
    ctrl.desactiver_immediat()
    snap = ETAT.snapshot()
    assert snap["actif"] is False and snap["mission"] == "" and snap["etat"] == "IDLE" and snap["progression"] == 0
    dernier = [e for e in hud_bridge.JOURNAL if e["t"] == "ghost"][-1]
    assert dernier["actif"] is False          # le HUD retire alors la classe body.ghost (verifie par Chromium)
    import hud
    assert hud._GHOST["etat"]["actif"] is False and not hud._GHOST_TERM


# 5-6 ---------------------------------------------------------------------------------------------------------
def test_05_voix_windows_en_mode_normal_sans_elevenlabs(tmp_path, voix_cfg):
    faux = FauxHTTP()
    p, _ = fournisseur(tmp_path, faux)
    voice_manager.remplacer_provider(p)
    assert voice_manager.provider_actif() is None            # core.tts.tts() garde son comportement habituel
    from core import tts as moteur_tts
    assert moteur_tts.tts() is not p
    assert faux.appels == [] and p.usage.caracteres == 0     # aucun appel, aucun quota consomme


def test_06_elevenlabs_en_mode_ghost(ctrl, tmp_path, voix_cfg):
    faux = FauxHTTP()
    p, _ = fournisseur(tmp_path, faux)
    voice_manager.remplacer_provider(p)
    ctrl.activer()
    from core import tts as moteur_tts
    assert moteur_tts.tts() is p
    audio, taux = p.synthetiser("Commandant, je suis opérationnel.")
    assert taux == 24000 and len(audio) == 2400 and ETAT.voix == VOIX_ELEVENLABS
    a = faux.appels[0]
    assert "voix-test" in a["url"] and a["entetes"]["xi-api-key"] == CLE_FACTICE
    assert b'"model_id"' in a["corps"] and b"voice_settings" in a["corps"] and a["timeout"] > 0
    # cache : la meme phrase n'est jamais regeneree ni recomptee
    p.synthetiser("Commandant, je suis opérationnel.")
    assert len(faux.appels) == 1 and p.usage.caracteres == len("Commandant, je suis opérationnel.")
    # messages techniques / vides : aucun appel
    assert p.synthetiser("ok") is None and p.synthetiser("   ") is None and len(faux.appels) == 1
    # texte long : tronque a la limite configuree
    p.synthetiser("Une phrase. " * 80)
    assert len(faux.appels[-1]["corps"]) < 700


# 7-10 --------------------------------------------------------------------------------------------------------
def test_07_cle_absente(ctrl, tmp_path, caplog):
    faux = FauxHTTP()
    p, _ = fournisseur(tmp_path, faux)
    voice_manager.remplacer_provider(p)
    ctrl.activer()
    assert p.synthetiser("Bonjour Commandant") is None and faux.appels == []
    assert ETAT.voix == VOIX_FALLBACK and p.dernier_genre == "cle_absente"
    assert ctrl.activer()                                     # Ghost reste utilisable


def test_08_cle_invalide(tmp_path, voix_cfg, caplog):
    caplog.set_level(logging.DEBUG)
    faux = FauxHTTP([(401, b'{"detail":{"status":"invalid_api_key"}}')])
    p, h = fournisseur(tmp_path, faux)
    ETAT.definir(actif=True)
    assert p.synthetiser("Phrase de test numéro un") is None
    assert p.dernier_genre == "cle_invalide" and ETAT.voix == VOIX_FALLBACK
    assert p.synthetiser("Phrase de test numéro deux") is None and len(faux.appels) == 1   # disjoncteur : pas de martelage
    assert CLE_FACTICE not in caplog.text                     # la cle n'est jamais journalisee
    assert CLE_FACTICE not in str(hud_bridge.JOURNAL)


def test_09_quota_epuise(tmp_path, voix_cfg):
    faux = FauxHTTP([(429, b'{"detail":{"status":"quota_exceeded"}}')])
    p, h = fournisseur(tmp_path, faux)
    assert p.synthetiser("Phrase de test quota") is None and p.dernier_genre == "quota"
    assert p.usage.caracteres == 0                            # un echec ne consomme rien dans NOTRE compteur


def test_10_repli_windows_puis_retour_ghost(tmp_path, voix_cfg):
    faux = FauxHTTP([ConnectionResetError, ])
    faux.reponses = [el.ErreurVoix("reseau", "coupure"), (200, b"AUDIO")]
    p, h = fournisseur(tmp_path, faux)
    assert p.synthetiser("Premiere phrase longue") is None            # None => jarvis14.dire() prend SAPI (Windows)
    assert ETAT.voix == VOIX_FALLBACK
    assert p.synthetiser("Deuxieme phrase longue") is None and len(faux.appels) == 1
    h.t += 61                                                          # delai de reessai ecoule
    assert p.synthetiser("Deuxieme phrase longue") is not None and ETAT.voix == VOIX_ELEVENLABS   # recuperation auto
    p2, _ = fournisseur(tmp_path, FauxHTTP([el.ErreurVoix("timeout", "lent")]))
    assert p2.synthetiser("Phrase timeout longue") is None and p2.dernier_genre == "timeout"
    p3, _ = fournisseur(tmp_path, FauxHTTP([(200, b"")]))
    assert p3.synthetiser("Phrase audio vide ici") is None


def test_10b_plafond_local_et_voix_coupee(ctrl, tmp_path, voix_cfg, monkeypatch):
    monkeypatch.setattr(cfg, "quota_mensuel", lambda: 30)
    faux = FauxHTTP()
    p, _ = fournisseur(tmp_path, faux)
    assert p.synthetiser("Ceci fait vingt-cinq lettres") is not None
    assert p.synthetiser("Une autre phrase assez longue") is None and len(faux.appels) == 1
    voice_manager.remplacer_provider(p)
    ctrl.activer()
    commandes.essayer("coupe la voix ghost", ctrl)
    assert type(voice_manager.provider_actif()).__name__ == "WindowsProvider"
    commandes.essayer("rétablis la voix ghost", ctrl)
    assert voice_manager.provider_actif() is p


# 11-12 -------------------------------------------------------------------------------------------------------
def test_11_pas_de_double_audio():
    """Structurel : un seul lecteur (dire) protege par un verrou ; un seul provider actif a la fois."""
    src = (RACINE / "jarvis14.py").read_text(encoding="utf-8")
    dire = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "dire")
    assert any(isinstance(n, ast.With) and "_VERROU_PAROLE" in ast.dump(n) for n in ast.walk(dire))
    assert "_VERROU_PAROLE = threading.RLock()" in src
    ETAT.definir(actif=True)
    assert voice_manager.provider_actif() is voice_manager.provider_actif()
    # le module Ghost ne joue jamais d'audio lui-meme
    for f in (RACINE / "modes" / "ghost_protocol").glob("*.py"):
        assert "sounddevice" not in f.read_text(encoding="utf-8") and "winsound" not in f.read_text(encoding="utf-8")


def test_12_communication_sse(ctrl):
    import hud, queue, json
    q = queue.Queue(maxsize=500)
    with hud._VERROU:
        hud._CLIENTS.add(q)
    try:
        ctrl.activer()
        ctrl.lancer_intelligence()
        attendre(ctrl)
        time.sleep(0.2)
        types = set()
        while not q.empty():
            types.add(json.loads(q.get())["t"])
    finally:
        with hud._VERROU:
            hud._CLIENTS.discard(q)
    assert {"ghost", "ghost_term", "ghost_mission", "ghost_rapport"} <= types
    assert hud._GHOST["etat"]["actif"] and len(hud._GHOST_TERM) > 0            # rejeu pour un client tardif
    hud.ghost("n'importe quoi"); hud.ghost({"t": "autre"})                     # entrees invalides : sans effet


# 13-14 -------------------------------------------------------------------------------------------------------
def test_13_generation_script_factice(ctrl):
    ctrl.activer()
    chemin = ctrl.generer_script()
    code = chemin.read_text(encoding="utf-8")
    assert len(code.splitlines()) >= 200 and "class " in code and "def " in code and "ProgressBar" in code
    assert "SIMULATION" in code.split('"""')[1] and "*** THIS IS A SIMULATION. ***" in code
    ok, pb = fcg.verifier_surete(code)
    assert ok, pb
    assert code != fcg.generer_script("autre-graine")                      # variation
    assert fcg.generer_script("x") == fcg.generer_script("x")              # deterministe par graine
    assert ETAT.script_genere and any(e["t"] == "ghost_script" for e in hud_bridge.JOURNAL)


@pytest.mark.parametrize("mauvais", [
    "import socket\nsocket.socket()", "import subprocess\nsubprocess.run(['x'])", "import os\nos.system('x')",
    "import requests", "from urllib.request import urlopen", "exec('1')", "open('f','w')", "__import__('socket')",
    "import ctypes", "import paramiko",
])
def test_14a_audit_rejette_le_dangereux(mauvais):
    ok, pb = fcg.verifier_surete(mauvais)
    assert not ok and pb


def test_14b_script_sans_aucune_connexion(ctrl, monkeypatch):
    # (1) statique : aucun module reseau importe, aucune adresse hors plages de documentation
    code = fcg.generer_script("audit")
    for banni in ("socket", "urllib", "requests", "http.client", "subprocess", "os.system"):
        assert f"import {banni}" not in code and f"from {banni}" not in code
    import re
    for ip in re.findall(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", code):
        assert ip.rsplit(".", 1)[0] in fi.PLAGES_DOC, ip
    # (2) dynamique : execution reelle sous garde ; toute tentative reseau/sous-processus leve une erreur
    ctrl.activer()
    ctrl.generer_script()
    proc = ctrl.run_script(rapide=True, attendre=True)
    assert proc is not None and proc.returncode == 0
    sortie = [e["texte"] for e in hud_bridge.JOURNAL if e["t"] == "ghost_term"]
    bloc = ["VIRTUAL TARGET : TEST_ENVIRONMENT", "SIMULATION     : COMPLETED", "DEVICE ACCESS  : NONE",
            "NETWORK ACCESS : NONE", "RESULT         : SUCCESS"]
    for ligne in bloc:
        assert ligne in sortie
    # (3) la garde bloque bel et bien le reseau, meme pour du code non audite
    piege = ctrl._dossier() / "piege.py"
    piege.write_text("import socket\ns = socket.socket()\ns.connect(('192.0.2.1', 80))\nprint('CONNECTE')\n")
    r = subprocess.run([sys.executable, "-I", "-c", controller._GARDE, str(piege)], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "CONNECTE" not in r.stdout and "GHOST SANDBOX" in r.stderr
    piege.write_text("import subprocess\nsubprocess.run(['echo','x'])\nprint('EXEC')\n")
    r = subprocess.run([sys.executable, "-I", "-c", controller._GARDE, str(piege)], capture_output=True, text=True, timeout=30)
    assert r.returncode != 0 and "EXEC" not in r.stdout


def test_14c_run_refuse_si_script_modifie(ctrl):
    ctrl.activer()
    chemin = ctrl.generer_script()
    chemin.write_text(chemin.read_text(encoding="utf-8") + "\nimport socket\n", encoding="utf-8")
    assert ctrl.run_script(rapide=True) is None


def test_14d_run_inactif(ctrl):
    assert ctrl.run_script() is None


# 15-16 -------------------------------------------------------------------------------------------------------
def test_15_fonctionne_sans_internet(ctrl, monkeypatch):
    def coupe(*a, **k):
        raise OSError("Internet coupe (test)")
    monkeypatch.setattr(socket.socket, "connect", coupe)
    monkeypatch.setattr(socket, "create_connection", coupe)
    monkeypatch.setattr(socket, "getaddrinfo", coupe)
    ctrl.activer()
    for lancer in (lambda: ctrl.lancer_recon("a.b@example.org"), ctrl.lancer_intelligence, ctrl.lancer_attack):
        assert lancer()
        attendre(ctrl)
        assert ctrl.moteur.etat == "COMPLETED"
    assert ctrl.run_script(rapide=True, attendre=True).returncode == 0
    assert commandes.essayer("désactive le mode hacker", ctrl)
    ctrl.finaliser_sortie()
    assert not ETAT.actif


def test_16_fonctionne_sans_llm(ctrl, monkeypatch):
    import core.llm as llm
    def hs(*a, **k):
        raise RuntimeError("fournisseur LLM en panne (test)")
    monkeypatch.setattr(llm, "llm", hs)
    from core import commandes_locales
    import modes.ghost_protocol as pkg
    monkeypatch.setattr(pkg, "_CTRL", [ctrl])
    assert commandes_locales.essayer("Jarvis, active le mode hacker")          # chemin REEL du routage local
    assert ETAT.actif
    assert commandes_locales.essayer("lance une analyse complète")
    attendre(ctrl)
    assert ctrl.moteur.etat == "COMPLETED"
    assert commandes_locales.essayer("désactive le mode hacker")
    ctrl.finaliser_sortie()
    assert not ETAT.actif


# 17 ----------------------------------------------------------------------------------------------------------
def test_17_compatibilite_existant(ctrl, monkeypatch):
    from core import commandes_locales
    import modes.ghost_protocol as pkg
    monkeypatch.setattr(pkg, "_CTRL", [ctrl])
    for phrase in ("quelle heure est-il", "allume la lumière du salon", "analyse cette cible", "lance une analyse complète",
                   "prépare une simulation d'intrusion", "désactive le mode nuit", "mets le mode gaming"):
        assert commandes.essayer(phrase, ctrl) is None, phrase          # Ghost inactif : phrases generiques ignorees
    assert not ETAT.actif
    assert commandes_locales.essayer("quelles voix sont disponibles") is not None   # commande existante intacte
    assert commandes_locales.essayer("désactive le mode nuit") != "Le mode Ghost n'est pas actif."
    # une phrase etrangere reste ignoree meme Ghost actif
    ctrl.activer()
    assert commandes.essayer("raconte-moi une blague", ctrl) is None
    # core.tts : aucune regression du chemin normal
    ctrl.desactiver_immediat()
    from core import tts as moteur_tts
    assert voice_manager.provider_actif() is None and moteur_tts.tts() is not None


# Complements ------------------------------------------------------------------------------------------------------
def test_simulation_progression_reelle_et_arret_propre(ctrl):
    ctrl.vitesse = 1.0
    ctrl.activer()
    assert ctrl.lancer_intelligence()
    assert "déjà" in ctrl.lancer_attack() or "en cours" in ctrl.lancer_attack()            # pas de double lancement
    time.sleep(0.6)
    assert 0 <= ETAT.progression < 1 and ETAT.etat_sim == "RUNNING"
    ctrl.desactiver()                                                                       # pendant l'animation
    assert not ctrl.moteur.en_cours
    assert ctrl.moteur.etat == "ABORTED"
    ctrl.finaliser_sortie()
    assert not ETAT.actif and ETAT.progression == 0


def test_progression_egale_etapes_terminees(ctrl):
    ctrl.activer()
    ctrl.lancer_intelligence()
    attendre(ctrl)
    mesures = [e["progression"] for e in hud_bridge.JOURNAL if e["t"] == "ghost_mission"]
    assert mesures[0] == 0 and mesures[-1] == 1 and set(mesures) >= {0.2, 0.4, 0.6, 0.8, 1.0}
    assert ETAT.menace in ("MODERATE", "ELEVATED", "HIGH")


def test_arret_simulation_vocal(ctrl):
    ctrl.vitesse = 1.0
    ctrl.activer()
    ctrl.lancer_intelligence()
    assert commandes.essayer("arrête la simulation", ctrl) in __import__("modes.ghost_protocol.responses", fromlist=["ARRET"]).ARRET
    assert ctrl.moteur.attendre(5) and ctrl.moteur.etat == "ABORTED"
    from modes.ghost_protocol import responses
    assert commandes.essayer("arrête la simulation", ctrl) in responses.AUCUNE


def test_recon_reel_vs_simule_et_ip_documentation():
    r = fi.rapport_recon("jean.dupont@gmail.com")
    assert "[REAL" in r and "[SIMULATED" in r and "UNVERIFIED" in r and "MODE         : CINEMATIC SIMULATION" in r
    d = fi.analyser_adresse("jean.dupont@gmail.com")
    assert d["format_valide"] and d["domaine"] == "gmail.com" and d["ip_fictive"].rsplit(".", 1)[0] in fi.PLAGES_DOC
    assert d == fi.analyser_adresse("jean.dupont@gmail.com")                                # deterministe
    assert not fi.analyser_adresse("pas une adresse")["format_valide"]
    assert fi.analyser_adresse("x@mailinator.com")["domaine_jetable"]
    assert "DEMO TARGET" in fi.rapport_recon("", demo=True)


def test_adresse_dictee_et_commandes_recon(ctrl):
    assert commandes.adresse_dictee("analyse jean arobase gmail point com") == "jean@gmail.com"
    ctrl.activer()
    commandes.essayer("lance Ghost Recon sur jean.dupont@gmail.com", ctrl)
    attendre(ctrl)
    rap = [e for e in hud_bridge.JOURNAL if e["t"] == "ghost_rapport"][-1]["texte"]
    assert "jean.dupont@gmail.com" in rap


def test_noms_explicites_hors_mode(ctrl):
    for p in ("lance Ghost Recon", "lance Ghost Intelligence"):
        assert "n'est pas actif" in commandes.essayer(p, ctrl)
    assert "n'est pas actif" in commandes.essayer("désactive le mode hacker", ctrl)


def test_pas_de_cle_dans_le_depot():
    import re
    motif = re.compile(r"sk_[0-9a-f]{20,}|xi-api-key\s*[:=]\s*['\"][A-Za-z0-9]{16,}")
    fichiers = list((RACINE / "modes").rglob("*.py")) + [RACINE / ".env.example", RACINE / "docs" / "GHOST_PROTOCOL.md"]
    for f in fichiers:
        if f.exists():
            assert not motif.search(f.read_text(encoding="utf-8")), f


def test_personnalite_ghost_reversible():
    from modes.ghost_protocol import personality
    assert personality.consigne(True) and personality.consigne(False) == ""
    assert "fictif" in personality.CONSIGNE_GHOST.lower() or "simul" in personality.CONSIGNE_GHOST.lower()


def test_cache_audio_lru(tmp_path):
    c = CacheAudio(tmp_path, 3000)
    for i in range(10):
        c.ecrire(c.cle(f"t{i}", "v", "m", {}), bytes(1000))
    assert sum(f.stat().st_size for f in tmp_path.iterdir() if f.is_file()) <= 3000
