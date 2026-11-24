"""Chef d'orchestre GHOST PROTOCOL : activation/desactivation reversibles, scenarios, script de demonstration.

Tout est local : aucun appel LLM ni reseau n'est necessaire pour activer, desactiver ou jouer un scenario.
La parole passe par ``parleur`` (jarvis14.dire, injecte) : un seul lecteur audio, donc jamais deux syntheses a la fois.
"""
from __future__ import annotations

import logging
import subprocess
import sys
import threading
import time

from modes.ghost_protocol import config, fake_code_generator, fake_intelligence, hud_bridge, responses
from modes.ghost_protocol.scenarios import SCENARIOS
from modes.ghost_protocol.simulation_engine import MoteurSimulation
from modes.ghost_protocol.state_manager import ETAT, VOIX_INCONNUE

LOG = logging.getLogger("jarvis.ghost")

# Garde du sous-processus : bloque tout reseau, sous-processus et ecriture, meme si le script etait modifie.
_GARDE = r'''
import sys, runpy
_BLOQUES = ("socket.", "subprocess.", "os.system", "os.exec", "os.spawn", "os.fork", "os.posix_spawn", "os.remove",
            "os.rename", "os.mkdir", "os.rmdir", "shutil.", "ctypes.", "winreg.", "webbrowser.")
def _hook(evt, args):
    if evt.startswith(_BLOQUES) or (evt == "open" and len(args) > 1 and isinstance(args[1], str) and any(c in args[1] for c in "wax+")):
        raise PermissionError("GHOST SANDBOX: operation interdite (" + evt + ")")
sys.addaudithook(_hook)
import socket as _s
def _no(*a, **k): raise PermissionError("GHOST SANDBOX: network access NONE")
_s.socket.connect = _no; _s.socket.connect_ex = _no; _s.create_connection = _no; _s.getaddrinfo = _no
path = sys.argv[1]; sys.argv = sys.argv[1:]
runpy.run_path(path, run_name="__main__")
'''


class GhostController:
    def __init__(self, vitesse: float = 1.0, parleur=None, hasard=None, dossier=None):
        self.vitesse = vitesse
        self.parleur = parleur
        self.rep = responses.Repertoire(hasard)
        self._verrou = threading.RLock()
        self.moteur = None
        self.dossier = dossier
        self.dernier_script = None
        self._sandbox = None
        self._arret_tele = threading.Event()
        self._fil_tele = None
        self._derniere_alerte = 0.0
        self.mesures = {}

    def definir_parleur(self, f):
        self.parleur = f

    def _dossier(self):
        return self.dossier or config.dossier_donnees()

    # --- activation / desactivation -------------------------------------------------------------------------
    def activer(self) -> str:
        with self._verrou:
            if ETAT.actif and not ETAT.sortie_en_attente:
                self.resynchroniser()                 # « insister » ne doit plus etre necessaire : on renvoie l'etat au HUD
                return self.rep.choisir("deja", responses.DEJA_ACTIF) + self._note_hud()
            hud_bridge.debut_session()
            ETAT.definir(actif=True, depuis=time.time(), sortie_en_attente=False, voix=VOIX_INCONNUE, mission="STANDBY",
                         etat_sim="IDLE", progression=0.0, menace="-")
            hud_bridge.etat(ETAT.snapshot())
            for t in ("GHOST PROTOCOL INITIALIZED", "TACTICAL ENVIRONMENT ONLINE", "SIMULATION MODE: LOCAL ONLY - NO NETWORK SCAN"):
                hud_bridge.terminal(t, "ok")
            hud_bridge.son("activation")
            self._demarrer_telemetrie()
            threading.Thread(target=self._sequence_boot, daemon=True, name="ghost-boot").start()
            return self.rep.choisir("activation", responses.ACTIVATION) + self._note_hud()

    def resynchroniser(self):
        """Renvoie l'etat courant au HUD (client en retard, page obsolete, evenement manque)."""
        hud_bridge.etat(ETAT.snapshot())

    @staticmethod
    def _note_hud() -> str:
        """Phrase d'avertissement si le serveur HUD tourne mais qu'AUCUN affichage n'est connecte (cause frequente du
        « Jarvis dit qu'il a change mais l'interface ne bouge pas »)."""
        try:
            import hud
            if getattr(hud, "_SERVEUR", None) is not None and hud.nb_clients() == 0:
                return " Attention : aucun affichage HUD n'est connecté. Ouvrez ou rechargez la fenêtre du HUD."
        except Exception:
            pass
        return ""

    def desactiver(self) -> str:
        """Annonce la sortie ; la bascule effective est faite par finaliser_sortie() apres la phrase d'adieu."""
        with self._verrou:
            if not ETAT.actif:
                self.resynchroniser()                 # HUD reste bloque en rouge alors que l'etat est normal : on le corrige
                return self.rep.choisir("inactif", responses.INACTIF)
            self._arreter_simulation()
            ETAT.definir(sortie_en_attente=True)
            hud_bridge.terminal("GHOST PROTOCOL SHUTDOWN SEQUENCE", "warn")
            return self.rep.choisir("desactivation", responses.DESACTIVATION)

    def finaliser_sortie(self) -> bool:
        with self._verrou:
            if not (ETAT.actif and ETAT.sortie_en_attente):
                return False
            self.desactiver_immediat()
            return True

    # --- telemetrie reelle, sequence de demarrage, rapport de situation ---------------------------------------
    def _demarrer_telemetrie(self):
        if self._fil_tele and self._fil_tele.is_alive():
            return
        self._arret_tele = threading.Event()
        self._fil_tele = threading.Thread(target=self._boucle_telemetrie, args=(self._arret_tele,), daemon=True, name="ghost-telemetry")
        self._fil_tele.start()

    def _boucle_telemetrie(self, arret, periode: float = 2.0):
        from modes.ghost_protocol import telemetry
        telemetry.lire()                                   # amorce les compteurs (cpu/reseau)
        chaud = 0
        while not arret.wait(periode):
            try:
                m = telemetry.lire()
                self.mesures = m
                hud_bridge.telemetrie(m)
                chaud = chaud + 1 if (m.get("cpu") or 0) > 90 else 0
                if chaud >= 2 and time.time() - self._derniere_alerte > 60:     # alerte REELLE, jamais spontanee a la voix
                    self._derniere_alerte = time.time()
                    hud_bridge.terminal(f"WARNING: CPU LOAD {m['cpu']:.0f} %", "warn")
                    hud_bridge.son("alerte")
            except Exception:
                LOG.exception("telemetrie Ghost")

    def _sequence_boot(self):
        """Affiche des verifications REELLES (voix, LLM, HUD, telemetrie, bac a sable) -- pas un decor."""
        pas = []
        pas.append(("GHOST CORE", "ONLINE", "ok"))
        try:
            import hud
            n = hud.nb_clients() if getattr(hud, "_SERVEUR", None) is not None else 0
            pas.append(("HUD LINK", f"{n} DISPLAY(S)" if n else "NO DISPLAY", "ok" if n else "warn"))
        except Exception:
            pas.append(("HUD LINK", "UNAVAILABLE", "warn"))
        if config.cle_api() and config.voice_id():
            pas.append(("VOICE ENGINE", "ELEVENLABS READY (key present, not yet tested)", "ok"))
        else:
            pas.append(("VOICE ENGINE", "WINDOWS (no ElevenLabs key/voice configured)", "warn"))
        try:
            from core.llm import llm
            f = llm()
            pas.append(("LLM ROUTER", f"{getattr(f, 'nom', '?')} {'READY' if f.disponible() else 'UNAVAILABLE'}",
                        "ok" if f.disponible() else "warn"))
        except Exception:
            pas.append(("LLM ROUTER", "UNAVAILABLE (local commands still work)", "warn"))
        try:
            import psutil  # noqa: F401
            pas.append(("TELEMETRY", "LIVE (psutil)", "ok"))
        except ImportError:
            pas.append(("TELEMETRY", "UNAVAILABLE (psutil missing)", "warn"))
        pas.append(("SANDBOX", "ARMED (network/process/write blocked)", "ok"))
        for lib, statut, niv in pas:
            if not ETAT.actif or ETAT.sortie_en_attente:
                return
            hud_bridge.boot(lib, statut, niv)
            time.sleep(0.35 / max(0.05, self.vitesse))

    def rapport_situation(self) -> str:
        from modes.ghost_protocol import telemetry
        m = telemetry.lire()
        hud_bridge.terminal("SITUATION REPORT: " + telemetry.resume_parle(m).split(": ", 1)[-1], "info")
        return self.rep.choisir("situation", responses.SITUATION_PREFIXE) + telemetry.resume_parle(m)

    def contexte_llm(self) -> str:
        """Ligne ajoutee au prompt du LLM tant que Ghost est actif : mesures REELLES, pour qu'il ne les invente pas."""
        m = self.mesures
        if not m:
            return ""
        return (f"Mesures systeme reelles a l'instant : CPU {m.get('cpu')} %, RAM {m.get('ram')} %, disque {m.get('disque')} %, "
                f"batterie {m.get('batterie')}. N'invente aucune autre mesure.")

    def desactiver_immediat(self):
        self._arret_tele.set()
        with self._verrou:
            self._arreter_simulation()
            self._tuer_sandbox()
            ETAT.remettre_a_zero()
            hud_bridge.etat(ETAT.snapshot())

    # --- scenarios ------------------------------------------------------------------------------------------
    def _arreter_simulation(self):
        m = self.moteur
        if m and m.en_cours:
            m.arreter()

    def arreter_simulation(self) -> str:
        m = self.moteur
        if m and m.en_cours:
            m.arreter()
            return self.rep.choisir("arret", responses.ARRET)
        return self.rep.choisir("aucune", responses.AUCUNE)

    def _lancer(self, cle: str, on_etape=None, on_fin_extra=None, menace="-") -> str:
        with self._verrou:
            if not ETAT.actif or ETAT.sortie_en_attente:
                return self.rep.choisir("inactif", responses.INACTIF)
            if self.moteur and self.moteur.en_cours:
                return self.rep.choisir("encours", responses.DEJA_EN_COURS)
            ETAT.definir(menace="-", progression=0.0, etat_sim="RUNNING")

            def fin(etat):
                if on_fin_extra and etat == "COMPLETED":
                    on_fin_extra()
                if etat == "COMPLETED" and ETAT.actif and not ETAT.sortie_en_attente and self.parleur:
                    try:
                        self.parleur(self.rep.choisir("fin_" + cle, responses.FIN[cle]))
                    except Exception:
                        LOG.exception("parole de fin")

            self.moteur = MoteurSimulation(SCENARIOS[cle], self.vitesse, on_etape, fin, menace).demarrer()
            return self.rep.choisir("debut_" + cle, responses.DEBUT[cle])

    def lancer_intelligence(self) -> str:
        graine = str(int(time.time()) // 60)
        menace = fake_intelligence.NIVEAUX[(fake_intelligence._empreinte(graine + "#i") % 3) + 1]
        return self._lancer("intelligence", menace=menace,
                            on_fin_extra=lambda: hud_bridge.rapport(fake_intelligence.rapport_intelligence(graine)))

    def lancer_recon(self, adresse: str = "") -> str:
        demo = not adresse
        cible = adresse or fake_intelligence.CIBLE_DEMO
        menace = fake_intelligence.analyser_adresse(cible)["menace"]
        return self._lancer("recon", menace=menace,
                            on_fin_extra=lambda: hud_bridge.rapport(fake_intelligence.rapport_recon(cible, demo)))

    def lancer_attack(self) -> str:
        def etape(i, e):
            if i == 1:
                self.generer_script()
        return self._lancer("attack", on_etape=etape, menace="SIMULATED")

    # --- script de demonstration ------------------------------------------------------------------------------
    def generer_script(self):
        code = fake_code_generator.generer_script(str(int(time.time())))
        ok, problemes = fake_code_generator.verifier_surete(code)
        if not ok:                                   # ne doit jamais arriver : on refuse de publier le script
            hud_bridge.terminal("SAFETY AUDIT FAILED: " + "; ".join(problemes), "erreur")
            raise RuntimeError("audit de surete du script Ghost refuse")
        chemin = self._dossier() / "ghost_attack_simulation.py"
        chemin.write_text(code, encoding="utf-8")
        self.dernier_script = chemin
        ETAT.definir(script_genere=str(chemin))
        hud_bridge.script_pret(chemin.name, len(code.splitlines()))
        hud_bridge.terminal(f"script ready: {chemin.name} ({len(code.splitlines())} lines, safety audit OK)", "ok")
        return chemin

    def run_script(self, rapide: bool = False, attendre: bool = False):
        """Execute le script de demonstration dans un sous-processus isole (reseau/sous-processus/ecriture bloques)."""
        with self._verrou:
            if not ETAT.actif or not self.dernier_script or not self.dernier_script.exists():
                return None
            if self._sandbox and self._sandbox.poll() is None:
                return None
            # reverification juste avant l'execution : le fichier peut avoir change sur le disque
            ok, pb = fake_code_generator.verifier_surete(self.dernier_script.read_text(encoding="utf-8"))
            if not ok:
                hud_bridge.terminal("SAFETY AUDIT FAILED: " + "; ".join(pb), "erreur")
                return None
            cmd = [sys.executable, "-I", "-c", _GARDE, str(self.dernier_script)] + (["--fast"] if rapide else [])
            try:
                from core.missions import environnement_sain
                env = environnement_sain()
            except Exception:
                env = {"PATH": "", "PYTHONDONTWRITEBYTECODE": "1"}
            self._sandbox = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                             env=env, cwd=str(self._dossier()), text=True, encoding="utf-8", errors="replace")
            proc = self._sandbox
        t = threading.Thread(target=self._lire_sortie, args=(proc,), daemon=True, name="ghost-sandbox")
        t.start()
        if attendre:
            t.join(70)
        return proc

    def _lire_sortie(self, proc):
        minuteur = threading.Timer(60.0, lambda: proc.poll() is None and proc.kill())
        minuteur.start()
        try:
            hud_bridge.terminal("RUN SIMULATION: sandbox started (network NONE)", "ok")
            for brut in proc.stdout:
                ligne = brut.replace("\r", "\n").strip().splitlines()
                if ligne:
                    hud_bridge.terminal(ligne[-1], "sim")
            proc.wait()
            hud_bridge.terminal(f"sandbox exit code {proc.returncode}", "ok" if proc.returncode == 0 else "erreur")
        finally:
            minuteur.cancel()

    def _tuer_sandbox(self):
        p = self._sandbox
        if p and p.poll() is None:
            p.kill()
