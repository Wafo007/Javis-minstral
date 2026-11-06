"""Moteur de simulation : deroule un Scenario dans un thread, sans jamais bloquer Jarvis ni toucher au reseau.

La progression publiee = etapes REELLEMENT terminees / nombre d'etapes (pas un compteur invente). Arret propre via
``arreter()`` (desactivation pendant l'animation). ``vitesse`` > 1 accelere (tests) ; rien d'autre n'est simule ici.
"""
from __future__ import annotations

import logging
import threading
import time

from modes.ghost_protocol import hud_bridge
from modes.ghost_protocol.state_manager import ETAT

LOG = logging.getLogger("jarvis.ghost")


class MoteurSimulation:
    def __init__(self, scenario, vitesse: float = 1.0, on_etape=None, on_fin=None, menace_finale="-"):
        self.scenario = scenario
        self.vitesse = max(0.01, float(vitesse))
        self.on_etape = on_etape            # on_etape(index, etape) : travail local reel eventuel
        self.on_fin = on_fin                # on_fin(etat) avec etat COMPLETED | ABORTED | FAILED
        self.menace_finale = menace_finale
        self._stop = threading.Event()
        self._thread = None
        self.etat = "IDLE"
        self.termine = threading.Event()

    @property
    def en_cours(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def demarrer(self):
        if self.en_cours:
            raise RuntimeError("simulation deja en cours")
        self.etat = "RUNNING"
        self._debut = time.time()
        self._thread = threading.Thread(target=self._boucle, name="ghost-sim", daemon=True)
        self._thread.start()
        return self

    def arreter(self, attendre_s: float = 3.0):
        self._stop.set()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(attendre_s)

    def attendre(self, delai: float = 10.0) -> bool:
        return self.termine.wait(delai)

    def _publier(self, progression):
        temps = time.time() - self._debut
        ETAT.definir(mission=self.scenario.mission, etat_sim=self.etat, progression=progression)
        hud_bridge.mission(self.scenario.nom, self.etat, progression, ETAT.menace, temps, ETAT.voix)

    def _boucle(self):
        etapes = self.scenario.etapes
        etat_final = "COMPLETED"
        try:
            hud_bridge.terminal(f"{self.scenario.nom} INITIALIZED", "ok")
            self._publier(0.0)
            for i, e in enumerate(etapes):
                if self._stop.is_set():
                    etat_final = "ABORTED"
                    break
                hud_bridge.terminal(e.titre + ("" if e.reel else " [SIMULATED]"), "info")
                if self.on_etape:
                    self.on_etape(i, e)
                for ligne in e.lignes:
                    if self._stop.wait(0.25 / self.vitesse):
                        break
                    hud_bridge.terminal("  " + ligne, "sim" if "SIMULATED" in ligne else "info")
                if self._stop.wait(max(0.0, e.duree_s) / self.vitesse):
                    etat_final = "ABORTED"
                    break
                self._publier((i + 1) / len(etapes))
        except Exception:
            LOG.exception("simulation Ghost")
            etat_final = "FAILED"
        self.etat = etat_final
        if etat_final == "COMPLETED":
            ETAT.definir(etat_sim="COMPLETED", progression=1.0, menace=self.menace_finale)
            hud_bridge.mission(self.scenario.nom, "COMPLETED", 1.0, self.menace_finale, time.time() - self._debut, ETAT.voix)
            hud_bridge.terminal(f"{self.scenario.nom} COMPLETED", "ok")
        else:
            ETAT.definir(etat_sim=etat_final)
            hud_bridge.mission(self.scenario.nom, etat_final, ETAT.progression, ETAT.menace, time.time() - self._debut, ETAT.voix)
            hud_bridge.terminal(f"{self.scenario.nom} {etat_final}", "warn")
        self.termine.set()
        if self.on_fin:
            try:
                self.on_fin(etat_final)
            except Exception:
                LOG.exception("fin de simulation Ghost")
