"""Missions autonomes d'auto-amelioration : persistance SQLite, machine a etats, horloge, supervision.

Jarvis recoit « ameliore ton routage, tu as 60 minutes » : une mission est creee (base SQLite hors du depot),
un workspace git isole (``git worktree`` sur une branche dediee) est prepare, puis un PROCESSUS SEPARE
(``scripts/mission_worker.py``) execute la boucle d'agent (``core/mission_agent.py``). La mission survit a la
fermeture de la fenetre de chat, a une coupure Internet, a une erreur API, a un plantage ou a un redemarrage :
tout l'etat utile est en base ; au redemarrage de Jarvis, ``reprendre_interrompues`` relance les missions dont
le processus a disparu, depuis le dernier point de controle coherent.

Mise en page (sous ``missions.racine``, par defaut ``%LOCALAPPDATA%/JarvisMissions`` sous Windows) ::

    missions.db                 base SQLite (missions, etapes, evenements, tests, mesures)
    workspaces/mission_001/     worktree git isole de la mission (jamais la version stable)
    reports/mission_001/        report.md, changes.diff, tests.json, execution.log

La version stable est le projet lui-meme : une mission n'y ecrit JAMAIS. L'integration passe par
``integrer_mission`` et exige une autorisation explicite (outil N3 « mission_integrer »).
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

LOG = logging.getLogger("jarvis.missions")

RACINE_PROJET = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------------------------------ etats
PENDING, RUNNING, PAUSED, WAITING_FOR_QUOTA, TESTING = "PENDING", "RUNNING", "PAUSED", "WAITING_FOR_QUOTA", "TESTING"
COMPLETED, PARTIAL, FAILED, CANCELLED, TIMEOUT = "COMPLETED", "PARTIAL", "FAILED", "CANCELLED", "TIMEOUT"
ETATS = (PENDING, RUNNING, PAUSED, WAITING_FOR_QUOTA, TESTING, COMPLETED, PARTIAL, FAILED, CANCELLED, TIMEOUT)
TERMINAUX = frozenset({COMPLETED, PARTIAL, FAILED, CANCELLED, TIMEOUT})
ACTIFS = frozenset({PENDING, RUNNING, PAUSED, WAITING_FOR_QUOTA, TESTING})
_FIN = {COMPLETED, PARTIAL, FAILED, CANCELLED, TIMEOUT}
TRANSITIONS = {
    PENDING: {RUNNING, CANCELLED, FAILED},
    RUNNING: {RUNNING, PAUSED, WAITING_FOR_QUOTA, TESTING} | _FIN,
    TESTING: {RUNNING, TESTING, PAUSED, WAITING_FOR_QUOTA} | _FIN,
    PAUSED: {RUNNING, TESTING, CANCELLED, TIMEOUT, PARTIAL, FAILED},
    WAITING_FOR_QUOTA: {RUNNING, TESTING, PAUSED, CANCELLED, TIMEOUT, PARTIAL, FAILED},
    **{e: set() for e in TERMINAUX},
}

DUREE_DEFAUT_MIN = 60
DUREE_MAX_MIN = 120
HEARTBEAT_PERIME_S = 90


class ErreurMission(RuntimeError):
    """Operation de mission refusee ; le message est lisible a voix haute."""


# ------------------------------------------------------------------------------------ configuration
def _reglage(chemin, defaut):
    try:
        from core.config import reglage
        v = reglage(chemin, None)
    except Exception:
        v = None
    return defaut if v is None else v


def racine_missions() -> Path:
    r = str(_reglage("missions.racine", "") or "")
    if r:
        return Path(r).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "JarvisMissions"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "jarvis_missions"


def borner_duree_min(minutes) -> float:
    """Duree configurable : defaut 60 min, plafond 120 min (un plafond, pas une obligation)."""
    try:
        m = float(minutes)
    except (TypeError, ValueError):
        m = float(_reglage("missions.duree_defaut_min", DUREE_DEFAUT_MIN))
    plafond = min(float(_reglage("missions.duree_max_min", DUREE_MAX_MIN)), DUREE_MAX_MIN)
    return max(1.0, min(m, plafond))


# --------------------------------------------------------------------------------------- horloge
class ChronoActif:
    """Temps ACTIF cumule d'une mission (monotone, insensible aux changements d'heure systeme).

    Les pauses et les attentes de quota ne comptent pas ; la valeur est sauvegardee a chaque point de controle
    et au battement de coeur, donc une reprise apres plantage repart du dernier temps connu (et ne
    redonne jamais le temps deja consomme).
    """

    def __init__(self, deja=0.0, horloge=time.monotonic):
        self._h = horloge
        self.deja = float(deja)
        self._t0 = None

    def demarrer(self):
        if self._t0 is None:
            self._t0 = self._h()

    def arreter(self):
        if self._t0 is not None:
            self.deja += max(0.0, self._h() - self._t0)
            self._t0 = None

    def ecoule(self) -> float:
        return self.deja + (max(0.0, self._h() - self._t0) if self._t0 is not None else 0.0)


# ------------------------------------------------------------------------------------------- base
_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions(
  id TEXT PRIMARY KEY, numero INTEGER UNIQUE, objectif TEXT NOT NULL, statut TEXT NOT NULL,
  duree_max_s REAL NOT NULL, temps_actif_s REAL NOT NULL DEFAULT 0,
  echeance_calendaire REAL, cree_le REAL, demarre_le REAL, termine_le REAL, maj_le REAL,
  depot TEXT, branche TEXT, workspace TEXT, rapports TEXT, base_commit TEXT, dernier_checkpoint TEXT,
  etape INTEGER NOT NULL DEFAULT 0, plan TEXT, budget TEXT, usage TEXT, reprise_a REAL,
  pid INTEGER, heartbeat REAL, pause_demandee INTEGER NOT NULL DEFAULT 0,
  annulation_demandee INTEGER NOT NULL DEFAULT 0, erreur TEXT, resume TEXT,
  autorisations TEXT, notification TEXT, notifie_voix INTEGER NOT NULL DEFAULT 0, etat_agent TEXT);
CREATE TABLE IF NOT EXISTS evenements(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission TEXT, ts REAL, type TEXT, donnees TEXT);
CREATE TABLE IF NOT EXISTS etapes(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission TEXT, n INTEGER, ts REAL, phase TEXT, action TEXT, cible TEXT,
  succes INTEGER, verifie INTEGER, tests TEXT, erreur TEXT, duree REAL, fournisseur TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS tests(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission TEXT, ts REAL, etape INTEGER, nature TEXT, commande TEXT,
  rc INTEGER, statut TEXT, duree REAL, stdout TEXT, stderr TEXT, resume TEXT);
CREATE TABLE IF NOT EXISTS mesures(
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission TEXT, ts REAL, nom TEXT, avant REAL, apres REAL, unite TEXT,
  commande TEXT);
CREATE INDEX IF NOT EXISTS ix_evt ON evenements(mission, id);
CREATE INDEX IF NOT EXISTS ix_etp ON etapes(mission, n);
"""
_CHAMPS_JSON = {"plan", "budget", "usage", "autorisations", "etat_agent"}


class MissionStore:
    """Acces SQLite (multi-processus : WAL + busy_timeout). Chaque appel ouvre/ferme sa connexion."""

    def __init__(self, racine=None):
        self.racine = (Path(racine) if racine else racine_missions()).expanduser().resolve()   # chemins ABSOLUS : les sous-processus changent de dossier
        self.racine.mkdir(parents=True, exist_ok=True)
        self.db = self.racine / "missions.db"
        with self._cx() as c:
            c.executescript(_SCHEMA)

    @contextlib.contextmanager
    def _cx(self):
        c = sqlite3.connect(str(self.db), timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            yield c
            c.commit()
        finally:
            c.close()

    # -- chemins ---------------------------------------------------------------------------------
    def dossier_workspace(self, mid) -> Path:
        return self.racine / "workspaces" / mid

    def dossier_rapports(self, mid) -> Path:
        return self.racine / "reports" / mid

    # -- missions --------------------------------------------------------------------------------
    @staticmethod
    def _decoder(row):
        if row is None:
            return None
        d = dict(row)
        for k in _CHAMPS_JSON:
            if d.get(k):
                try:
                    d[k] = json.loads(d[k])
                except ValueError:
                    d[k] = None
        return d

    def creer(self, objectif, duree_s, depot, calendaire_s=None) -> str:
        with self._cx() as c:
            c.execute("BEGIN IMMEDIATE")
            n = (c.execute("SELECT COALESCE(MAX(numero),0) FROM missions").fetchone()[0] or 0) + 1
            mid = f"mission_{n:03d}"
            now = time.time()
            cal = float(calendaire_s) if calendaire_s else max(float(_reglage("missions.delai_calendaire_max_h", 24)) * 3600,
                                                              duree_s * 2)
            c.execute("INSERT INTO missions(id,numero,objectif,statut,duree_max_s,echeance_calendaire,cree_le,maj_le,"
                      "depot,rapports) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (mid, n, objectif, PENDING, float(duree_s), now + cal, now, now, str(depot),
                       str(self.dossier_rapports(mid))))
        self.evenement(mid, "creee", {"objectif": objectif, "duree_max_s": duree_s})
        return mid

    def get(self, mid) -> dict | None:
        with self._cx() as c:
            return self._decoder(c.execute("SELECT * FROM missions WHERE id=?", (mid,)).fetchone())

    def lister(self, actives_seulement=False, limite=20) -> list[dict]:
        with self._cx() as c:
            rows = c.execute("SELECT * FROM missions ORDER BY numero DESC LIMIT ?", (int(limite),)).fetchall()
        res = [self._decoder(r) for r in rows]
        return [m for m in res if m["statut"] in ACTIFS] if actives_seulement else res

    def derniere(self, actives_seulement=False) -> dict | None:
        res = self.lister(actives_seulement, 1 if not actives_seulement else 20)
        return res[0] if res else None

    def maj(self, mid, **champs):
        if not champs:
            return
        champs["maj_le"] = time.time()
        for k in list(champs):
            if k in _CHAMPS_JSON and not isinstance(champs[k], (str, type(None))):
                champs[k] = json.dumps(champs[k], ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in champs)
        with self._cx() as c:
            c.execute(f"UPDATE missions SET {cols} WHERE id=?", (*champs.values(), mid))

    def transition(self, mid, nouvel, **champs):
        """Change d'etat en validant la transition ; ErreurMission si elle est incoherente."""
        with self._cx() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT statut FROM missions WHERE id=?", (mid,)).fetchone()
            if row is None:
                raise ErreurMission(f"Mission inconnue : {mid}")
            actuel = row["statut"]
            if nouvel not in ETATS:
                raise ErreurMission(f"Etat inconnu : {nouvel}")
            if nouvel != actuel and nouvel not in TRANSITIONS.get(actuel, set()):
                raise ErreurMission(f"Transition interdite : {actuel} -> {nouvel}")
            if nouvel in TERMINAUX and "termine_le" not in champs:
                champs["termine_le"] = time.time()
            champs["statut"], champs["maj_le"] = nouvel, time.time()
            for k in list(champs):
                if k in _CHAMPS_JSON and not isinstance(champs[k], (str, type(None))):
                    champs[k] = json.dumps(champs[k], ensure_ascii=False)
            cols = ", ".join(f"{k}=?" for k in champs)
            c.execute(f"UPDATE missions SET {cols} WHERE id=?", (*champs.values(), mid))
        if nouvel != actuel:
            self.evenement(mid, "etat", {"de": actuel, "vers": nouvel})

    # -- journal, etapes, tests --------------------------------------------------------------------
    def evenement(self, mid, type_, donnees=None):
        with self._cx() as c:
            c.execute("INSERT INTO evenements(mission,ts,type,donnees) VALUES(?,?,?,?)",
                      (mid, time.time(), type_, json.dumps(donnees or {}, ensure_ascii=False, default=str)))

    def evenements(self, mid, limite=2000):
        with self._cx() as c:
            return [dict(r) for r in c.execute(
                "SELECT * FROM evenements WHERE mission=? ORDER BY id LIMIT ?", (mid, limite)).fetchall()]

    def etape(self, mid, n, phase, action, cible, succes, verifie, tests=None, erreur=None, duree=0.0,
              fournisseur="", detail=""):
        with self._cx() as c:
            c.execute("INSERT INTO etapes(mission,n,ts,phase,action,cible,succes,verifie,tests,erreur,duree,fournisseur,detail)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (mid, n, time.time(), phase, action, cible, int(bool(succes)), int(bool(verifie)),
                       json.dumps(tests or []), erreur, float(duree), fournisseur, str(detail)[:2000]))

    def etapes(self, mid):
        with self._cx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM etapes WHERE mission=? ORDER BY id", (mid,)).fetchall()]

    def test(self, mid, etape, nature, commande, rc, statut, duree, stdout, stderr, resume=""):
        with self._cx() as c:
            c.execute("INSERT INTO tests(mission,ts,etape,nature,commande,rc,statut,duree,stdout,stderr,resume)"
                      " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      (mid, time.time(), etape, nature, json.dumps(commande), rc, statut, float(duree),
                       (stdout or "")[-6000:], (stderr or "")[-3000:], resume))

    def tests(self, mid):
        with self._cx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM tests WHERE mission=? ORDER BY id", (mid,)).fetchall()]

    def mesure(self, mid, nom, avant, apres, unite, commande):
        with self._cx() as c:
            c.execute("INSERT INTO mesures(mission,ts,nom,avant,apres,unite,commande) VALUES(?,?,?,?,?,?,?)",
                      (mid, time.time(), nom, avant, apres, unite, commande))

    def mesures(self, mid):
        with self._cx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM mesures WHERE mission=? ORDER BY id", (mid,)).fetchall()]


# ----------------------------------------------------------------------------------- processus
def processus_vivant(pid) -> bool:
    if not pid:
        return False
    try:
        import psutil
        if not psutil.pid_exists(int(pid)):
            return False
        return psutil.Process(int(pid)).status() != psutil.STATUS_ZOMBIE
    except ImportError:
        try:
            os.kill(int(pid), 0)
            return True
        except OSError:
            return False
    except Exception:
        return False


def worker_vivant(m) -> bool:
    return bool(m and processus_vivant(m.get("pid"))
                and (time.time() - float(m.get("heartbeat") or 0)) < HEARTBEAT_PERIME_S)


def tuer_arbre(pid, delai=5.0):
    """Arrete proprement un processus et ses enfants (terminate puis kill)."""
    if not pid:
        return
    try:
        import psutil
        try:
            p = psutil.Process(int(pid))
        except psutil.NoSuchProcess:
            return
        procs = p.children(recursive=True) + [p]
        for q in procs:
            with contextlib.suppress(psutil.Error):
                q.terminate()
        _, vivants = psutil.wait_procs(procs, timeout=delai)
        for q in vivants:
            with contextlib.suppress(psutil.Error):
                q.kill()
    except ImportError:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        else:
            with contextlib.suppress(OSError):
                os.kill(int(pid), 15)


def environnement_sain(base=None) -> dict:
    """Environnement minimal pour les sous-processus de mission : aucune cle/secret herite."""
    base = dict(base if base is not None else os.environ)
    sensibles = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "COOKIE", "AUTH")
    # GIT_CONFIG_* est retire EN BLOC : filtrer seulement GIT_CONFIG_KEY_n (nom « sensible ») laisserait un
    # GIT_CONFIG_COUNT orphelin et git echouerait partout (constate sur une vraie mission).
    env = {k: v for k, v in base.items()
           if not any(m in k.upper() for m in sensibles) and not k.upper().startswith("GIT_CONFIG")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"          # pas de .pyc dans le workspace (diff et checkpoints propres)
    return env


def lancer_worker(store: MissionStore, mid: str) -> int:
    """Lance le worker en processus detache (independant de la fenetre de chat et de Jarvis)."""
    script = RACINE_PROJET / "scripts" / "mission_worker.py"
    dossier = store.dossier_rapports(mid)
    dossier.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(script), mid, "--racine", str(store.racine)]
    kw = {"cwd": str(RACINE_PROJET), "env": environnement_sain(), "stdin": subprocess.DEVNULL}
    log = open(dossier / "worker.log", "ab")
    kw["stdout"] = kw["stderr"] = log
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200 | 0x08000000     # DETACHED | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kw["start_new_session"] = True
    proc = subprocess.Popen(cmd, **kw)
    log.close()
    store.maj(mid, pid=proc.pid, heartbeat=time.time())
    store.evenement(mid, "worker_lance", {"pid": proc.pid})
    return proc.pid


# ------------------------------------------------------------------------------- API de haut niveau
def demarrer_mission(objectif: str, duree_min=None, depot=None, store: MissionStore | None = None,
                     lancer=True, duree_s=None) -> dict:
    """Cree la mission + son workspace isole et lance le worker. Renvoie la ligne de mission."""
    from core import auto_modification as am
    objectif = " ".join(str(objectif or "").split())
    if len(objectif) < 8:
        raise ErreurMission("Je n'ai pas compris l'objectif de la mission : dis-moi quoi ameliorer.")
    store = store or MissionStore()
    depot = Path(depot or RACINE_PROJET).resolve()
    actives = [m for m in store.lister(True) if m["statut"] != PAUSED]
    maxi = int(_reglage("missions.max_simultanees", 1))
    if len(actives) >= maxi:
        raise ErreurMission(f"Une mission est deja en cours ({actives[0]['id']}) : "
                            "termine-la, mets-la en pause ou annule-la d'abord.")
    if duree_s is None:
        duree_s = borner_duree_min(duree_min) * 60.0
    mid = store.creer(objectif, duree_s, depot)
    try:
        branche = f"jarvis/{mid}"
        if am._git(depot, "branch", "--list", branche, check=False).stdout.strip():     # base de missions remise a zero
            branche += time.strftime("-%Y%m%d-%H%M%S")
        info = am.creer_workspace(depot, store.dossier_workspace(mid), branche)
    except Exception as exc:
        store.transition(mid, FAILED, erreur=f"creation du workspace impossible : {exc}")
        raise ErreurMission(f"Je n'ai pas pu preparer l'espace de travail isole : {exc}") from exc
    store.maj(mid, branche=branche, workspace=info["workspace"], base_commit=info["base"],
              dernier_checkpoint=info["base"],
              budget=_budgets_par_defaut(),
              usage={"requetes": 0, "tokens": 0})
    store.evenement(mid, "workspace_pret", {"branche": branche, "base": info["base"][:10],
                                            "fichiers_recopies": len(info["fichiers_recopies"])})
    if lancer:
        lancer_worker(store, mid)
    return store.get(mid)


def _budgets_par_defaut() -> dict:
    return {"max_requetes": int(_reglage("missions.budget_requetes", 400)),
            "max_tokens": int(_reglage("missions.budget_tokens", 1_500_000)),
            "max_etapes": int(_reglage("missions.budget_etapes", 120)),
            "max_tentatives_etape": int(_reglage("missions.tentatives_par_etape", 3))}


def _cible(store, mid=None, actives=True):
    m = store.get(mid) if mid else store.derniere(actives_seulement=actives) or (store.derniere() if not actives else None)
    if not m:
        raise ErreurMission("Je n'ai aucune mission en cours." if actives else "Je n'ai aucune mission enregistree.")
    return m


def mettre_en_pause(store, mid=None) -> dict:
    m = _cible(store, mid)
    if m["statut"] in TERMINAUX:
        raise ErreurMission(f"La mission {m['id']} est deja terminee ({m['statut']}).")
    if m["statut"] == PAUSED:
        return m
    store.maj(m["id"], pause_demandee=1)
    if not worker_vivant(m):                          # pas de worker : on peut poser l'etat directement
        store.transition(m["id"], PAUSED, pause_demandee=0, pid=None)
    store.evenement(m["id"], "pause_demandee")
    return store.get(m["id"])


def reprendre(store, mid=None, lancer=True) -> dict:
    m = _cible(store, mid, actives=True)
    if m["statut"] in TERMINAUX:
        raise ErreurMission(f"La mission {m['id']} est terminee ({m['statut']}) : rien a reprendre.")
    store.maj(m["id"], pause_demandee=0)
    store.evenement(m["id"], "reprise_demandee")
    if not worker_vivant(m) and lancer:
        lancer_worker(store, m["id"])
    return store.get(m["id"])


def annuler(store, mid=None, urgence=False) -> dict:
    """Annule : drapeau d'annulation (le worker s'arrete proprement) ; urgence = arret immediat des processus."""
    m = _cible(store, mid)
    if m["statut"] in TERMINAUX:
        raise ErreurMission(f"La mission {m['id']} est deja terminee ({m['statut']}).")
    store.maj(m["id"], annulation_demandee=1)
    store.evenement(m["id"], "annulation_demandee", {"urgence": bool(urgence)})
    if urgence or not worker_vivant(m):
        tuer_arbre(m.get("pid"))
        store.transition(m["id"], CANCELLED, pid=None,
                         resume="arret d'urgence" if urgence else "annulee (aucun processus actif)")
        try:
            from core.mission_rapport import generer_rapport
            generer_rapport(store, m["id"])
        except Exception:
            LOG.exception("rapport d'annulation")
    return store.get(m["id"])


def reprendre_interrompues(store: MissionStore | None = None, lancer=True) -> list[str]:
    """Au demarrage de Jarvis : relance les missions actives dont le worker a disparu (plantage, reboot).

    Les missions en pause restent en pause. Renvoie les identifiants relances.
    """
    store = store or MissionStore()
    relancees = []
    for m in store.lister(True):
        if m["statut"] == PAUSED or worker_vivant(m):
            continue
        if m["statut"] == PENDING and not m.get("workspace"):
            store.transition(m["id"], FAILED, erreur="mission interrompue avant la creation du workspace")
            continue
        store.evenement(m["id"], "interrompue_detectee", {"etat": m["statut"], "pid": m.get("pid")})
        if lancer:
            lancer_worker(store, m["id"])
        relancees.append(m["id"])
    return relancees


def integrer_mission(store, mid=None, autorise=False) -> dict:
    """Integre le candidat verifie dans la version stable. Refuse sans autorisation explicite (N3)."""
    from core import auto_modification as am
    m = _cible(store, mid, actives=False)
    if m["statut"] not in {COMPLETED, PARTIAL}:
        raise ErreurMission(f"La mission {m['id']} est {m['statut']} : rien de verifie a integrer.")
    try:
        res = am.integrer(m["depot"], m["workspace"], m["base_commit"], autorise=autorise)
    except am.ErreurAutoModif as exc:
        raise ErreurMission(str(exc)) from exc
    store.evenement(m["id"], "integree", res)
    return res


# --------------------------------------------------------------------------------------- statut vocal
def _fmt_duree(s) -> str:
    s = int(max(0, s))
    return f"{s // 60} min" if s >= 60 else f"{s} s"


def resume_statut(m: dict, store: MissionStore) -> str:
    """Phrase de statut pour la voix, construite UNIQUEMENT depuis la base (rien n'est suppose)."""
    etapes = store.etapes(m["id"])
    modifs = {e["cible"] for e in etapes if e["action"] in ("write_file", "replace_in_file", "delete_file")
              and e["succes"]}
    base = (f"Mission {m['numero']} (« {m['objectif'][:70]} ») : {m['statut'].lower().replace('_', ' ')}. "
            f"{_fmt_duree(m['temps_actif_s'])} sur {_fmt_duree(m['duree_max_s'])}, étape {m['etape']}, "
            f"{len(modifs)} fichier(s) modifié(s).")
    if m["statut"] == WAITING_FOR_QUOTA and m.get("reprise_a"):
        base += f" Quota atteint : reprise vers {time.strftime('%H:%M', time.localtime(m['reprise_a']))}."
    if m["statut"] in TERMINAUX and m.get("resume"):
        base += f" {m['resume']}"
    elif etapes:
        d = etapes[-1]
        base += f" Dernière action : {d['action']} {d['cible'] or ''}".rstrip() + (" (échec)." if not d["succes"] else ".")
    return base


# ------------------------------------------------------------------------------------- notification
def notifier(titre: str, texte: str, plateforme=None, executeur=subprocess.run) -> tuple[bool, str]:
    """Notification Windows (info-bulle). Renvoie (emise, detail) ; echec = NON livree, jamais masque.

    Une notification « emise » signifie que le mecanisme a repondu sans erreur : on ne peut pas verifier
    que l'utilisatrice l'a vue. Hors Windows ou en cas d'erreur, la notification est consideree non livree.
    """
    plateforme = plateforme or os.name
    if plateforme != "nt":
        return False, "notification Windows indisponible sur cette plateforme"
    esc = lambda s: str(s).replace("'", "''")[:200]                         # noqa: E731
    script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
              "$n = New-Object System.Windows.Forms.NotifyIcon; $n.Icon = [System.Drawing.SystemIcons]::Information; "
              f"$n.Visible = $true; $n.ShowBalloonTip(15000, '{esc(titre)}', '{esc(texte)}', 'Info'); "
              "Start-Sleep -Seconds 16; $n.Dispose()")
    try:
        r = executeur(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script],
                      capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"echec de la notification : {exc}"
    if r.returncode != 0:
        return False, f"echec de la notification (code {r.returncode}) : {(r.stderr or '')[:150]}"
    return True, "info-bulle emise (non confirmee visuellement)"


def messages_a_annoncer(store: MissionStore) -> list[tuple[str, str]]:
    """Missions terminees dont la fin n'a pas ete annoncee a voix haute (a appeler depuis Jarvis)."""
    res = []
    for m in store.lister(False, 10):
        if m["statut"] in TERMINAUX and not m["notifie_voix"]:
            res.append((m["id"], f"Mission terminée : {m['statut'].lower()}. {m.get('resume') or ''} "
                                 f"Le rapport est prêt, dis « montre-moi ton rapport »."))
    return res


def marquer_annoncee(store, mid):
    store.maj(mid, notifie_voix=1)
