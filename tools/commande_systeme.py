"""Executer des commandes du systeme (PowerShell / shell) : le « corps » le plus general de Jarvis.

Taper dans un terminal au clavier est fragile (focus, verrouillage, relecture impossible). Ici Jarvis lance
la commande LUI-MEME, lit sa sortie et son code retour, et peut donc installer, creer, deplacer, lancer un
script, utiliser git ou pip... et VERIFIER le resultat.

Trois niveaux, decides par ``classer_commande`` AVANT toute execution :
- « interdite » : jamais executee (formatage de disque, effacement recursif de la racine, extinction
  deguisee, telechargement-execution, desactivation de l'antivirus...). Aucune confirmation ne la debloque ;
- « risquee » : suppression, arret de processus/services, registre, reseau, installation/desinstallation de
  logiciels, planificateur... -> outil ``executer_commande_risquee`` (N3 : confirmation vocale CHAQUE fois) ;
- « sure » : lecture, creation, copie, execution de scripts du projet, git/pip en lecture... -> outil
  ``executer_commande`` (N2 : confirmation memorisable, revocable, ou dispense via securite.toujours).
Jamais exposes au MCP ni a distance.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path

from core.config import reglage
from core.registre import outil
from core.resultat import ResultatOutil

LOG = logging.getLogger("jarvis.commande")
_SORTIE_MAX = 4000

# Jamais executees, quoi que dise l'utilisateur ou le modele.
_INTERDITES = [
    r"\bformat(?:-volume)?\s+[a-z]:", r"\bdiskpart\b", r"\bbcdedit\b", r"\bcipher\s+/w", r"\bvssadmin\s+delete",
    r"\bwevtutil\s+cl\b", r"\bclear-eventlog\b", r"\bset-mppreference\b.*disable", r"\bdisable-windowsoptionalfeature\b",
    r"\bnet\s+user\b.*\s/add", r"\bnet\s+localgroup\s+administrators\b", r"-enc(?:odedcommand)?\b",
    r"\b(?:iex|invoke-expression)\b.*\b(?:iwr|invoke-webrequest|downloadstring|irm|invoke-restmethod)\b",
    r"\b(?:iwr|curl|wget|invoke-webrequest)\b[^|;]*\|\s*(?:iex|sh|bash|powershell|cmd)\b",
    r"\brm\s+-[a-z]*r[a-z]*f?[a-z]*\s+(?:/|~|\*|[a-z]:\\?\s*$)", r"\bremove-item\b[^;|]*\s[a-z]:\\?\s*(?:-|$)",
    r"\bdel\s+/[a-z]*s[^|;]*\s[a-z]:\\", r"\brd\s+/s\b[^|;]*\s[a-z]:\\?\s*$", r"\bmkfs\b", r"\bdd\s+if=.*of=/dev/",
    r":\(\)\s*\{", r"\bshutdown\b", r"\bstop-computer\b", r"\brestart-computer\b", r"\bhalt\b", r"\bpoweroff\b",
    r"\bset-executionpolicy\s+(?:unrestricted|bypass)", r"\bnetsh\s+advfirewall\b.*\boff\b",
    r"\breg\s+(?:delete|add)\s+hk(?:lm|ey_local_machine)", r"\bcmdkey\b", r"\bmimikatz\b",
]
# Executables seulement apres confirmation vocale a chaque fois.
_RISQUEES = [
    r"\b(?:rm|del|erase|rd|rmdir|remove-item|ri|unlink|shred)\b", r"\bmove-item\b|\bmv\b\s", r"\bformat\b(?!-)",
    r"\b(?:taskkill|stop-process|kill|pkill|killall)\b", r"\b(?:stop|restart|set|remove)-service\b|\bsc\s+(?:stop|delete|config)\b|\bnet\s+(?:stop|start|user|use)\b",
    r"\breg\s+(?:add|delete|import)\b|\bset-itemproperty\b.*hk|\bnew-itemproperty\b|\bremove-itemproperty\b",
    r"\b(?:winget|choco|scoop|apt(?:-get)?|brew|dnf|yum)\s+(?:install|uninstall|remove|upgrade)\b",
    r"\bpip3?\s+(?:install|uninstall)\b|\buv\s+(?:add|remove|pip\s+(?:install|uninstall))\b|\bnpm\s+(?:install|uninstall|i)\b",
    r"\bschtasks\b|\bregister-scheduledtask\b|\bcrontab\b", r"\bnetsh\b|\bnew-netfirewallrule\b|\bset-netfirewallrule\b",
    r"\bicacls\b|\btakeown\b|\bchmod\b|\bchown\b|\bsudo\b|\brunas\b|\bstart-process\b[^;|]*-verb\s+runas",
    r"\bgit\s+(?:push|reset\s+--hard|clean|checkout\s+--|branch\s+-d|rebase|force)\b", r"\bgit\b[^;|]*--force\b",
    r"\binvoke-webrequest\b|\biwr\b|\binvoke-restmethod\b|\birm\b|\bcurl\b|\bwget\b|\bscp\b|\bssh\b|\bftp\b",
    r"\bsend-mailmessage\b|\bnet\s+send\b", r"\bset-content\b[^;|]*\bhosts\b|\\drivers\\etc\\hosts",
    r">\s*(?:/dev/|[a-z]:\\windows)", r"\bout-file\b[^;|]*[a-z]:\\windows", r"\bsetx\b|\[environment\]::setenvironmentvariable",
]
_INTERDITES_RE = [re.compile(p, re.I) for p in _INTERDITES]
_RISQUEES_RE = [re.compile(p, re.I) for p in _RISQUEES]


def classer_commande(commande: str) -> str:
    """« interdite », « risquee » ou « sure » (analyse statique, avant toute execution)."""
    texte = " ".join(str(commande or "").replace("`", " ").split())
    if not texte:
        return "interdite"
    if any(r.search(texte) for r in _INTERDITES_RE):
        return "interdite"
    if any(r.search(texte) for r in _RISQUEES_RE):
        return "risquee"
    return "sure"


def _dossier(dossier: str) -> Path:
    base = Path(str(dossier or "").strip()).expanduser() if str(dossier or "").strip() else Path.home()
    if not base.is_dir():
        raise FileNotFoundError(f"dossier introuvable : {base}")
    return base


def _lancer(commande: str, dossier: str, delai: float) -> ResultatOutil:
    try:
        cwd = _dossier(dossier)
    except OSError as exc:
        return ResultatOutil(str(exc), succes=False, erreur="dossier")
    if os.name == "nt":
        cmd = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command",
               "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; " + commande]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        cmd, env, flags = ["/bin/sh", "-c", commande], os.environ.copy(), 0
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=delai, env=env, creationflags=flags,
                           stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return ResultatOutil(f"La commande a depasse {int(delai)} s : je l'ai arretee.", succes=False, verifie=True,
                             erreur="delai")
    except OSError as exc:
        return ResultatOutil(f"Impossible de lancer la commande : {exc}", succes=False, erreur="lancement")
    sortie = (r.stdout or b"").decode("utf-8", "replace").strip()
    erreur = (r.stderr or b"").decode("utf-8", "replace").strip()
    brut = sortie + (("\n[erreurs]\n" + erreur) if erreur else "")
    if len(brut) > _SORTIE_MAX:
        brut = brut[:_SORTIE_MAX] + f"\n[... tronque : {len(brut)} caracteres]"
    if r.returncode == 0:
        return ResultatOutil(f"Commande terminee (code 0).\n{brut}".strip(), succes=True, verifie=True,
                             details={"code": 0, "dossier": str(cwd)})
    return ResultatOutil(f"La commande a echoue (code {r.returncode}).\n{brut}".strip(), succes=False, verifie=True,
                         erreur="code_retour", details={"code": r.returncode, "dossier": str(cwd)})


def _delai(valeur) -> float:
    try:
        return max(5.0, min(float(valeur or reglage("systeme.commande_delai", 60) or 60), 900.0))
    except (TypeError, ValueError):
        return 60.0


def _annonce(args):
    c = " ".join(str((args or {}).get("commande", "")).split())[:140]
    return f"Je vais executer la commande : {c}."


_PARAMS = {"type": "object", "properties": {
    "commande": {"type": "string", "description": "Commande PowerShell (Windows) ou shell, UNE ligne ou plusieurs separees par ; ."},
    "dossier": {"type": "string", "description": "Dossier de travail (defaut : dossier personnel)."},
    "delai": {"type": "number", "description": "Secondes max (60 par defaut)."}},
    "required": ["commande"]}


@outil(
    nom="executer_commande",
    description="EXECUTE une commande systeme (PowerShell sous Windows) et lit sa sortie : lister/creer/copier des "
                "fichiers, lancer un script Python, git status, pip list, ipconfig, systeminfo, ouvrir un dossier... "
                "C'est l'outil pour tout ce qui est « sur le PC » et qui n'a pas d'outil dedie, bien plus fiable que "
                "taper dans un terminal. Les commandes dangereuses (suppression, installation, registre, arret de "
                "processus, reseau) sont refusees ici : utilise executer_commande_risquee (confirmation vocale).",
    parametres=_PARAMS, confirmation=True, annonce=_annonce, lent=True,
    phrase_attente="Je lance la commande.",
)
def executer_commande(commande: str, dossier: str = "", delai: float = 0) -> str:
    classe = classer_commande(commande)
    if classe == "interdite":
        LOG.warning("commande interdite refusee : %s", " ".join(str(commande).split())[:200])
        return ResultatOutil("Cette commande est interdite (destructrice ou dangereuse pour le systeme) : je ne "
                             "l'execute pas, meme avec ta permission.", succes=False, erreur="interdite")
    if classe == "risquee":
        return ResultatOutil("Cette commande modifie ou supprime des choses : utilise executer_commande_risquee, qui "
                             "demande ta confirmation vocale.", succes=False, erreur="risquee")
    LOG.info("commande sure : %s", " ".join(str(commande).split())[:200])
    return _lancer(commande, dossier, _delai(delai))


@outil(
    nom="executer_commande_risquee",
    description="Execute une commande systeme qui SUPPRIME, installe, desinstalle, arrete un processus ou un service, "
                "modifie le registre, le reseau ou les droits (rm, del, Remove-Item, taskkill, winget install, pip "
                "install, git push...). Confirmation vocale OBLIGATOIRE a chaque fois (jamais « toujours »). "
                "Les commandes interdites (formatage, extinction, telechargement-execution...) restent refusees.",
    parametres=_PARAMS, confirmation=True, annonce=lambda a: "ATTENTION, commande risquee. " + _annonce(a), lent=True,
    phrase_attente="Je lance la commande.",
)
def executer_commande_risquee(commande: str, dossier: str = "", delai: float = 0) -> str:
    classe = classer_commande(commande)
    if classe == "interdite":
        LOG.warning("commande interdite refusee : %s", " ".join(str(commande).split())[:200])
        return ResultatOutil("Cette commande est interdite (destructrice ou dangereuse pour le systeme) : je ne "
                             "l'execute pas, meme avec ta permission.", succes=False, erreur="interdite")
    LOG.warning("commande risquee confirmee : %s", " ".join(str(commande).split())[:200])
    return _lancer(commande, dossier, _delai(delai))
