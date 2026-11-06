"""Generateur du script de demonstration GHOST ATTACK (simulation 100 % locale et fictive) + audit de surete statique.

Le script est compose a partir d'un modele fixe (aucun LLM : un LLM ne produit jamais du code que l'on execute ici).
Il ne contient ni import reseau, ni sous-processus, ni ecriture de fichier, ni eval/exec : ``verifier_surete`` le
verifie par analyse de l'AST, et le controleur ne l'execute que dans un sous-processus isole dont les sockets sont bloques.
"""
from __future__ import annotations

import ast
import hashlib

INTERDITS_IMPORT = {"socket", "ssl", "requests", "urllib", "urllib3", "http", "httpx", "aiohttp", "ftplib", "smtplib",
                    "telnetlib", "paramiko", "subprocess", "os", "shutil", "ctypes", "multiprocessing", "asyncio",
                    "selectors", "pty", "webbrowser", "importlib", "pickle", "marshal", "winreg", "pathlib", "io",
                    "tempfile", "glob", "xmlrpc", "socketserver", "scapy", "nmap"}
AUTORISES_IMPORT = {"time", "random", "hashlib", "json", "sys", "enum", "dataclasses", "typing", "textwrap", "__future__"}
APPELS_INTERDITS = {"eval", "exec", "compile", "__import__", "open", "input", "getattr", "setattr", "globals", "locals",
                    "vars", "breakpoint"}
FIN_ATTENDUE = ("GHOST ATTACK SIMULATION\n--------------------------------\nVIRTUAL TARGET : TEST_ENVIRONMENT\n"
                "SIMULATION     : COMPLETED\nDEVICE ACCESS  : NONE\nNETWORK ACCESS : NONE\nRESULT         : SUCCESS\n"
                "--------------------------------")

_MODELE = '''#!/usr/bin/env python3
"""GHOST ATTACK SIMULATION  --  DEMONSTRATION SCRIPT (seed @SEED@)

*** THIS IS A SIMULATION. ***
Everything below runs on an in-memory VIRTUAL environment named TEST_ENVIRONMENT.
It opens no network connection, touches no device, reads and writes no file, runs no command and
exploits nothing. Addresses are strings from documentation-only ranges (RFC 5737). Results are scripted.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

SIMULATION = True
NETWORK_ACCESS = "NONE"
DEVICE_ACCESS = "NONE"
SEED = "@SEED@"
FAST = "--fast" in sys.argv
RNG = random.Random(SEED)


def pause(seconds: float) -> None:
    """Cosmetic delay for the demo (skipped with --fast)."""
    if not FAST:
        time.sleep(seconds)


def log(level: str, message: str) -> None:
    print(f"[{level:<5}] {message}")


class Phase(Enum):
    BOOT = "BOOT"
    RECON = "RECON"
    ASSESS = "ASSESS"
    REPORT = "REPORT"
    DONE = "DONE"


class SimulationError(Exception):
    """Raised for scripted, harmless demo errors."""


@dataclass
class VirtualService:
    name: str
    port: int
    banner: str
    exposure: str = "SIMULATED"


@dataclass
class VirtualHost:
    hostname: str
    address: str
    services: List[VirtualService] = field(default_factory=list)

    def describe(self) -> str:
        return f"{self.hostname} ({self.address}) services={len(self.services)}"


def build_virtual_environment() -> VirtualHost:
    host = VirtualHost("TEST_ENVIRONMENT", "@IP@")
    for name, port, banner in @SERVICES@:
        host.services.append(VirtualService(name, port, banner))
    return host


class ProgressBar:
    def __init__(self, label: str, total: int = 20) -> None:
        self.label = label
        self.total = total

    def play(self) -> None:
        for step in range(self.total + 1):
            filled = "#" * step + "." * (self.total - step)
            print(f"\\r{self.label:<28} [{filled}] {int(100 * step / self.total):3d}%", end="", flush=True)
            pause(0.03)
        print()


class StateMachine:
    ORDER = [Phase.BOOT, Phase.RECON, Phase.ASSESS, Phase.REPORT, Phase.DONE]

    def __init__(self) -> None:
        self.phase = Phase.BOOT
        self.history: List[str] = []

    def advance(self) -> Phase:
        index = self.ORDER.index(self.phase)
        if index >= len(self.ORDER) - 1:
            raise SimulationError("state machine already finished")
        self.phase = self.ORDER[index + 1]
        self.history.append(self.phase.value)
        log("STATE", f"-> {self.phase.value}")
        return self.phase


class ReconModule:
    """Simulated reconnaissance: reads only the in-memory virtual host."""

    def __init__(self, host: VirtualHost) -> None:
        self.host = host

    def play(self) -> Dict[str, str]:
        ProgressBar("virtual reconnaissance").play()
        findings: Dict[str, str] = {}
        for service in self.host.services:
            fingerprint = hashlib.sha256(f"{service.name}{service.port}{SEED}".encode()).hexdigest()[:10]
            findings[service.name] = f"port {service.port} banner='{service.banner}' fp={fingerprint}"
            log("RECON", f"{service.name:<10} {findings[service.name]}")
            pause(0.05)
        return findings


class AssessmentEngine:
    """Scripted evaluation: scores are drawn from a seeded generator, they measure nothing real."""

    LEVELS = ["LOW", "MODERATE", "ELEVATED", "HIGH"]

    def score(self, findings: Dict[str, str]) -> Dict[str, str]:
        ProgressBar("simulated assessment").play()
        result: Dict[str, str] = {}
        for name in findings:
            result[name] = self.LEVELS[RNG.randrange(len(self.LEVELS))]
            log("EVAL", f"{name:<10} simulated exposure = {result[name]}")
            pause(0.04)
        return result


class ReportBuilder:
    def __init__(self, host: VirtualHost) -> None:
        self.host = host
        self.sections: List[str] = []

    def add(self, title: str, body: str) -> None:
        self.sections.append(f"== {title} ==\\n{body}")

    def render(self) -> str:
        header = f"REPORT FOR {self.host.describe()}"
        return header + "\\n" + "\\n".join(self.sections)


def scripted_error_demo() -> None:
    """Shows error handling with a harmless, scripted failure."""
    try:
        raise SimulationError("virtual module 'phantom' not found (scripted)")
    except SimulationError as error:
        log("WARN", f"handled: {error}")


def checksum(data: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


class AuditTrail:
    """Keeps an in-memory journal of the simulated run (nothing is written to disk)."""

    def __init__(self) -> None:
        self.entries: List[str] = []

    def record(self, source: str, message: str) -> None:
        stamp = f"T+{len(self.entries):03d}"
        self.entries.append(f"{stamp} {source}: {message}")

    def summary(self) -> str:
        return f"{len(self.entries)} journal entries (in memory only)"


def self_check() -> bool:
    """Confirms the demo is wired to the virtual environment only."""
    host = build_virtual_environment()
    ok = host.hostname == "TEST_ENVIRONMENT" and len(host.services) > 0
    log("CHECK", f"virtual environment sane: {ok}")
    return ok


def main() -> int:
    if not SIMULATION or NETWORK_ACCESS != "NONE" or DEVICE_ACCESS != "NONE":
        log("FATAL", "safety flags altered: refusing to run")
        return 2
    log("INFO", "GHOST ATTACK SIMULATION starting (virtual target only)")
    if not self_check():
        return 3
    trail = AuditTrail()
    trail.record("main", "simulation started")
    machine = StateMachine()
    host = build_virtual_environment()
    log("INFO", "virtual environment: " + host.describe())
    machine.advance()
    findings = ReconModule(host).play()
    machine.advance()
    scores = AssessmentEngine().score(findings)
    scripted_error_demo()
    machine.advance()
    report = ReportBuilder(host)
    report.add("FINDINGS (SIMULATED)", "\\n".join(f"{k}: {v}" for k, v in findings.items()))
    report.add("EXPOSURE (SIMULATED)", "\\n".join(f"{k}: {v}" for k, v in scores.items()))
    report.add("INTEGRITY", f"checksum={checksum(findings)} phases={'>'.join(machine.history)}")
    trail.record("main", "report rendered")
    print(report.render())
    log("INFO", trail.summary())
    machine.advance()
    print()
    print("GHOST ATTACK SIMULATION")
    print("--------------------------------")
    print("VIRTUAL TARGET : TEST_ENVIRONMENT")
    print("SIMULATION     : COMPLETED")
    print("DEVICE ACCESS  : NONE")
    print("NETWORK ACCESS : NONE")
    print("RESULT         : SUCCESS")
    print("--------------------------------")
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

_SERVICES = [
    [("web-demo", 8080, "demo-httpd/0.1"), ("db-demo", 5432, "demo-sql/0.2"), ("cache-demo", 6379, "demo-kv/0.3"),
     ("auth-demo", 8443, "demo-auth/0.1")],
    [("api-demo", 9000, "demo-api/1.0"), ("queue-demo", 5672, "demo-mq/0.4"), ("files-demo", 2121, "demo-ftp/0.1")],
    [("portal-demo", 8081, "demo-portal/2.0"), ("sql-demo", 3306, "demo-db/0.9"), ("mail-demo", 2525, "demo-smtp/0.2"),
     ("dns-demo", 5353, "demo-dns/0.1"), ("vault-demo", 8200, "demo-vault/0.1")],
]


def generer_script(graine: str = "") -> str:
    """Script de demonstration complet (>= 200 lignes), varie selon la graine, deterministe pour une graine donnee."""
    graine = graine or hashlib.sha256(b"ghost").hexdigest()[:8]
    h = int(hashlib.sha256(graine.encode()).hexdigest()[:8], 16)
    ip = f"{('192.0.2', '198.51.100', '203.0.113')[h % 3]}.{(h >> 8) % 253 + 1}"
    code = _MODELE.replace("@SEED@", graine).replace("@IP@", ip).replace("@SERVICES@", repr(_SERVICES[h % len(_SERVICES)]))
    return code


def verifier_surete(code: str) -> tuple[bool, list[str]]:
    """Audit statique : imports en liste blanche, aucun appel dangereux, aucun nom de reseau. (ok, problemes)."""
    problemes = []
    try:
        arbre = ast.parse(code)
    except SyntaxError as exc:
        return False, [f"syntaxe invalide : {exc}"]
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            for a in n.names:
                mod = a.name.split(".")[0]
                if mod in INTERDITS_IMPORT or mod not in AUTORISES_IMPORT:
                    problemes.append(f"import interdit : {a.name}")
        elif isinstance(n, ast.ImportFrom):
            mod = (n.module or "").split(".")[0]
            if mod in INTERDITS_IMPORT or mod not in AUTORISES_IMPORT:
                problemes.append(f"import interdit : {n.module}")
        elif isinstance(n, ast.Call):
            f = n.func
            nom = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if nom in APPELS_INTERDITS or nom in {"system", "popen", "Popen", "run", "check_output", "urlopen", "connect",
                                                    "create_connection", "socket", "getaddrinfo", "write_text",
                                                    "write_bytes", "unlink", "remove", "rmdir", "mkdir", "chmod"}:
                problemes.append(f"appel interdit : {nom}")
        elif isinstance(n, ast.Attribute) and n.attr in {"__subclasses__", "__globals__", "__builtins__", "__code__"}:
            problemes.append(f"acces interdit : {n.attr}")
    return (not problemes), problemes
