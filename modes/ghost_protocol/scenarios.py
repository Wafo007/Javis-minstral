"""Scenarios cinematographiques : listes d'etapes. Aucune operation reseau : tout est local et simule.

Chaque etape porte des lignes de terminal ; l'attribut ``reel`` distingue ce qui est reellement calcule localement
(analyse de format d'une adresse) de ce qui est une mise en scene. La progression affichee = etapes reellement
terminees / etapes du scenario.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Etape:
    titre: str
    lignes: tuple = ()
    duree_s: float = 1.2
    reel: bool = False                      # True : calcul local reel ; False : mise en scene simulee
    voix: str = ""                          # phrase courte eventuellement prononcee (0 par defaut : economie de quota)


@dataclass(frozen=True)
class Scenario:
    cle: str
    nom: str
    mission: str
    etapes: tuple = field(default_factory=tuple)


INTELLIGENCE = Scenario("intelligence", "GHOST INTELLIGENCE", "COMPLETE THREAT ANALYSIS (SIMULATED)", (
    Etape("INITIALIZING INTELLIGENCE ENGINE", ("loading core modules ... OK", "engine profile: SIMULATION"), 1.4),
    Etape("LOADING VIRTUAL DATABASE", ("mounting virtual dataset (in-memory) ... OK", "records: 1 284 (synthetic)"), 1.6),
    Etape("ANALYZING SIMULATED INDICATORS", ("correlating synthetic indicators ...", "cluster A : 17 events",
                                            "cluster B : 4 events"), 2.0),
    Etape("GENERATING THREAT ASSESSMENT", ("weighting indicators ...", "assessment model: DEMO-HEURISTIC"), 1.6),
    Etape("PREPARING FINAL REPORT", ("compiling report ...", "labelling REAL / SIMULATED fields ... OK"), 1.2),
))

RECON = Scenario("recon", "GHOST RECON", "TARGET RECONNAISSANCE (CINEMATIC SIMULATION)", (
    Etape("PARSING ADDRESS FORMAT", ("syntax check on local machine ...",), 1.0, reel=True),
    Etape("INSPECTING DOMAIN STRUCTURE", ("labels / TLD check (offline) ...",), 1.0, reel=True),
    Etape("SIMULATED OSINT SWEEP", ("[SIMULATED] sweeping virtual sources ...", "[SIMULATED] no real lookup performed"), 1.8),
    Etape("THREAT SCORING", ("[SIMULATED] scoring indicators ...",), 1.4),
    Etape("ANALYSIS COMPLETED", ("rendering report ...",), 0.8),
))

ATTACK = Scenario("attack", "GHOST ATTACK", "INTRUSION SIMULATION - VIRTUAL TARGET ONLY", (
    Etape("PREPARING VIRTUAL TEST ENVIRONMENT", ("allocating TEST_ENVIRONMENT (in-memory) ... OK",
                                                "network access: NONE", "device access: NONE"), 1.4),
    Etape("GENERATING SIMULATION SCRIPT", ("composing demo modules ...", "static safety audit ..."), 1.6, reel=True),
    Etape("SCRIPT READY", ("script saved locally", "press RUN SIMULATION to execute (sandboxed, offline)"), 0.8, reel=True),
))

SCENARIOS = {s.cle: s for s in (INTELLIGENCE, RECON, ATTACK)}
