"""Telemetrie systeme REELLE (psutil) pour le HUD Ghost et les rapports de situation. Aucune valeur inventee :
si une mesure est indisponible, elle vaut None et le HUD affiche « n/a »."""
from __future__ import annotations

import time

_PREC = {"t": None, "env": None, "recu": None}


def lire() -> dict:
    """Instantane : cpu %, ram %, ram utilisee (Go), disque %, batterie %, debit reseau local (Ko/s), processus, uptime (s)."""
    out = {"cpu": None, "ram": None, "ram_go": None, "disque": None, "batterie": None, "branche": None,
           "net_ko_s": None, "processus": None, "uptime_s": None, "ts": time.time()}
    try:
        import psutil
    except ImportError:
        return out
    try:
        out["cpu"] = round(psutil.cpu_percent(interval=None), 1)
        vm = psutil.virtual_memory()
        out["ram"], out["ram_go"] = round(vm.percent, 1), round(vm.used / 1024 ** 3, 2)
        out["processus"] = len(psutil.pids())
        out["uptime_s"] = int(time.time() - psutil.boot_time())
    except Exception:
        pass
    try:
        import os
        out["disque"] = round(psutil.disk_usage(os.path.abspath(os.sep)).percent, 1)
    except Exception:
        pass
    try:
        b = psutil.sensors_battery()
        if b is not None:
            out["batterie"], out["branche"] = round(b.percent), bool(b.power_plugged)
    except Exception:
        pass
    try:
        io = psutil.net_io_counters()
        now = time.time()
        if _PREC["t"] is not None and now > _PREC["t"]:
            out["net_ko_s"] = round(((io.bytes_sent - _PREC["env"]) + (io.bytes_recv - _PREC["recu"])) / 1024 / (now - _PREC["t"]), 1)
        _PREC.update(t=now, env=io.bytes_sent, recu=io.bytes_recv)
    except Exception:
        pass
    return out


def resume_parle(t: dict | None = None) -> str:
    """Phrase de rapport de situation fondee uniquement sur les mesures disponibles."""
    t = t or lire()
    morceaux = []
    if t.get("cpu") is not None:
        morceaux.append(f"processeur à {t['cpu']:.0f} pour cent")
    if t.get("ram") is not None:
        morceaux.append(f"mémoire à {t['ram']:.0f} pour cent")
    if t.get("disque") is not None:
        morceaux.append(f"disque à {t['disque']:.0f} pour cent")
    if t.get("batterie") is not None:
        morceaux.append(f"batterie à {t['batterie']} pour cent" + ("" if t.get("branche") else ", sur batterie"))
    if not morceaux:
        return "Je n'ai accès à aucune mesure système pour le moment, Commandant."
    alertes = []
    if (t.get("cpu") or 0) > 85:
        alertes.append("charge processeur élevée")
    if (t.get("ram") or 0) > 90:
        alertes.append("mémoire presque saturée")
    if (t.get("disque") or 0) > 95:
        alertes.append("disque presque plein")
    fin = ("Anomalies : " + ", ".join(alertes) + ".") if alertes else "Aucune anomalie détectée."
    return "Rapport de situation : " + ", ".join(morceaux) + ". " + fin
