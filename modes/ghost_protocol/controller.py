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

    def definir_parleur(self, f):
        self.parleur = f

    def _dossier(self):
        return self.dossier or config.dossier_donnees()

    # --- activation / desactivation -------------------------------------------------------------------------
    def activer(self) -> str:
        with self._verrou:
            if ETAT.actif and not ETAT.sortie_en_attente:
                return self.rep.choisir("deja", responses.DEJA_ACTIF)
            hud_bridge.debut_session()
            ETAT.definir(actif=True, depuis=time.time(), sortie_en_attente=False, voix=VOIX_INCONNUE, mission="STANDBY",
                         etat_sim="IDLE", progression=0.0, menace="-")
            hud_bridge.etat(ETAT.snapshot())
            for t in ("GHOST PROTOCOL INITIALIZED", "TACTICAL ENVIRONMENT ONLINE", "SIMULATION MODE: LOCAL ONLY - NO NETWORK SCAN"):
                hud_bridge.terminal(t, "ok")
            return self.rep.choisir("activation", responses.ACTIVATION)

    def desactiver(self) -> str:
        """Annonce la sortie ; la bascule effective est faite par finaliser_sortie() apres la phrase d'adieu."""
        with self._verrou:
            if not ETAT.actif:
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

    def desactiver_immediat(self):
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
