"""Statistiques systeme : GPU (temperature, usage, VRAM), CPU, RAM, disque.

GPU via pynvml (nvidia-ml-py) pour la carte NVIDIA ; le reste via psutil.
Le resultat complet est renvoye au LLM, qui repond de facon courte et
naturelle selon la question ("ma temperature GPU ?" -> juste le GPU).
"""
from core.registre import outil


@outil(
    nom="get_system_stats",
    mcp_expose=True,
    description="Donne l'etat de la machine : temperature et usage du GPU, VRAM, "
                "usage CPU, RAM, espace disque. A utiliser pour 'ma temperature GPU', "
                "'ca va niveau perfs', 'combien de RAM utilisee', 'il reste combien "
                "de disque'. Reponds de facon courte selon ce qui est demande.",
)
def get_system_stats() -> str:
    parties = []

    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
        util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        vram = round(mem.used / mem.total * 100) if mem.total else 0
        pynvml.nvmlShutdown()
        parties.append(f"GPU {temp} degres, {util}% d'utilisation, VRAM a {vram}%")
    except Exception:
        parties.append("GPU indisponible (pilote NVIDIA ou pynvml absent)")

    try:
        import psutil
        cpu = round(psutil.cpu_percent(interval=0.3))
        ram = round(psutil.virtual_memory().percent)
        disque = psutil.disk_usage("C:\\")
        libre = round(disque.free / (1024 ** 3))
        parties.append(f"CPU {cpu}%, RAM {ram}%, disque C {libre} Go libres")
    except Exception:
        parties.append("stats systeme indisponibles")

    return ". ".join(parties) + "."
