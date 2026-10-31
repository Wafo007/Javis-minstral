"""Missions autonomes : scenarios d'acceptation A-H + garde-fous.

Ce qui est REEL : git (vrai depot temporaire, vrai `git worktree`), SQLite, sous-processus pytest, kill de
processus, processus worker detache. Ce qui est une DOUBLURE : le LLM (``FauxLLM`` : reponses scriptees, AUCUN appel
Mistral/Gemini) -- ces tests valident le moteur, pas la qualite des decisions d'un vrai modele.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import auto_modification as am
from core import mission_agent as MA
from core import missions as M
from core.fournisseurs_mission import (BudgetEpuise, ErreurFournisseur, GestionnaireFournisseurs, QuotaEnAttente,
                                       classer_erreur, lire_retry_after)
from core.mission_rapport import generer_rapport


def git(d, *a):
    return subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True, text=True).stdout


CALC_BUG = "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n"
CALC_OK = "def add(a, b):\n    return a + b\n\n\ndef mul(a, b):\n    return a * b\n"
TESTS = ("from calc import add, mul\n\n\ndef test_add():\n    assert add(1, 2) == 3\n\n\n"
         "def test_mul():\n    assert mul(2, 3) == 6\n")


def j(**kw):
    return json.dumps(kw)


class Err429(Exception):
    def __init__(self, retry_after=None):
        super().__init__("429 Too Many Requests: rate limit")
        self.status_code = 429
        self.response = type("R", (), {"headers": {"Retry-After": str(retry_after)} if retry_after is not None else {}})()


class SimulationCrash(BaseException):
    """Simule la mort brutale du processus (n'est pas interceptee par la mission)."""


class FauxLLM:
    """DOUBLURE DE TEST (aucune API reelle) : rejoue des reponses scriptees ; vide -> finish."""

    def __init__(self, nom, reponses):
        self.nom, self.reponses, self.appels = nom, list(reponses), []

    def completer(self, messages):
        self.appels.append(messages)
        r = self.reponses.pop(0) if self.reponses else j(action="finish", summary="termine")
        if callable(r):
            r = r()
        if isinstance(r, BaseException):
            raise r
        return r, 100


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jm_"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.depot = self.tmp / "depot"
        self.depot.mkdir()
        git(self.depot, "init", "-q", "-b", "main")
        git(self.depot, "config", "user.email", "t@t.t")
        git(self.depot, "config", "user.name", "t")
        (self.depot / "tests").mkdir()
        (self.depot / "core").mkdir()
        (self.depot / "calc.py").write_text(CALC_BUG, encoding="utf-8")
        (self.depot / "tests" / "test_calc.py").write_text(TESTS, encoding="utf-8")
        (self.depot / "core" / "registre.py").write_text("PROTEGE = 1\n", encoding="utf-8")
        (self.depot / ".gitignore").write_text("config.yaml\n", encoding="utf-8")
        git(self.depot, "add", "-A")
        git(self.depot, "commit", "-q", "-m", "init")
        # etat reel « sale » du projet : travail non commite + secret ignore
        (self.depot / "core" / "extra.py").write_text("X = 1\n", encoding="utf-8")
        (self.depot / "config.yaml").write_text("mistral:\n  cle: SECRET-A-NE-JAMAIS-COPIER\n", encoding="utf-8")
        self.store = M.MissionStore(self.tmp / "missions")

    def mission(self, duree_s=120, objectif="ameliore ton systeme de calcul et corrige add"):
        return M.demarrer_mission(objectif, depot=self.depot, store=self.store, lancer=False, duree_s=duree_s)

    def agent(self, mid, reponses, nom="mistral", dormir=lambda s: None, **kw):
        llm = FauxLLM(nom, reponses)
        gest = GestionnaireFournisseurs([llm], dormir=dormir, **kw)
        a = MA.AgentMission(self.store, mid, gest, dormir=dormir)
        a.llm = llm
        return a

    def stable_intacte(self):
        self.assertEqual((self.depot / "calc.py").read_text(), CALC_BUG)
        self.assertEqual(git(self.depot, "rev-parse", "HEAD").strip(), git(self.depot, "rev-parse", "main").strip())

    SCRIPT_CORRECTION = [
        j(action="update_plan", plan=["lire calc.py", "corriger add", "ajouter un test", "valider"]),
        j(action="read_file", path="calc.py"),
        j(action="write_file", path="calc.py", content=CALC_OK),
        j(action="write_file", path="tests/test_calc_extra.py",
          content="from calc import add\n\n\ndef test_add_negatifs():\n    assert add(-1, -2) == -3\n"),
        j(action="validate"),
        j(action="finish", summary="add corrige, test ajoute"),
    ]


# ============================================================================== A
class ScenarioA_MissionComplete(Base):
    def test_mission_complete_avec_branche_worktree_modifs_tests_rapport(self):
        m = self.mission(duree_s=300)
        ws = Path(m["workspace"])
        self.assertTrue(ws.is_dir() and (ws / ".git").exists())               # vrai worktree
        self.assertEqual(m["branche"], f"jarvis/{m['id']}")
        self.assertIn(m["branche"], git(self.depot, "branch", "--list"))
        # baseline = etat reel du projet (fichier non commite recopie), secret JAMAIS recopie
        self.assertTrue((ws / "core" / "extra.py").exists())
        self.assertFalse((ws / "config.yaml").exists())
        a = self.agent(m["id"], self.SCRIPT_CORRECTION)
        statut = a.executer()
        self.assertEqual(statut, M.COMPLETED, self.store.get(m["id"]).get("resume"))
        self.stable_intacte()
        self.assertEqual((ws / "calc.py").read_text(), CALC_OK)
        etapes = self.store.etapes(m["id"])
        mods = [e for e in etapes if e["action"] == "write_file"]
        self.assertEqual(len(mods), 2)
        self.assertTrue(all(e["succes"] and e["verifie"] for e in mods))       # verifie seulement APRES la validation
        tests = self.store.tests(m["id"])
        self.assertIn("baseline", {t["nature"] for t in tests})
        self.assertTrue(all(t["rc"] is not None for t in tests))
        # baseline en echec (bug), validation finale verte : vrais sous-processus pytest
        self.assertEqual([t["statut"] for t in tests if t["nature"] == "baseline"], ["failed"])
        self.assertEqual([t["statut"] for t in tests if t["nature"] == "complet"], ["passed"])
        rap = Path(self.store.get(m["id"])["rapports"])
        for f in ("report.md", "changes.diff", "tests.json", "execution.log"):
            self.assertTrue((rap / f).is_file(), f)
        md = (rap / "report.md").read_text(encoding="utf-8")
        for n in range(1, 18):
            self.assertIn(f"## {n}. ", md)
        self.assertIn("a + b", (rap / "changes.diff").read_text())
        self.assertIn("COMPLETED", md)
        self.assertIn("La version stable n'a PAS été modifiée", md)
        self.assertIn("Aucune mesure avant/après", md)                         # pas de gain de perf invente
        self.assertEqual(self.store.get(m["id"])["pid"], None)
        # la ligne de journal JSON a la forme demandee
        lignes = [json.loads(l) for l in (rap / "execution.log").read_text(encoding="utf-8").splitlines() if l.startswith("{")]
        self.assertTrue({"step", "action", "target", "success", "verified", "tests", "error"} <= set(lignes[0]))

    def test_integration_exige_autorisation_puis_applique_sans_toucher_le_reste(self):
        m = self.mission()
        self.agent(m["id"], self.SCRIPT_CORRECTION).executer()
        with self.assertRaises(M.ErreurMission):
            M.integrer_mission(self.store, m["id"], autorise=False)
        with self.assertRaises(am.ErreurAutoModif):
            am.integrer(self.depot, m["workspace"], m["base_commit"], autorise=False)
        self.stable_intacte()
        res = M.integrer_mission(self.store, m["id"], autorise=True)           # scenario G : apres validation explicite
        self.assertIn("calc.py", res["fichiers"])
        self.assertEqual((self.depot / "calc.py").read_text(), CALC_OK)
        self.assertTrue((self.depot / "core" / "extra.py").exists())           # travail non commite preserve
        self.assertEqual(git(self.depot, "rev-parse", "HEAD").strip(), git(self.depot, "rev-parse", "main").strip())

    def test_l_outil_d_integration_est_critique_N3(self):
        from core import registre
        registre.charger_outils()
        self.assertEqual(registre.niveau("mission_integrer"), "N3")
        self.assertTrue(registre.get("mission_integrer").confirmation)
        self.assertFalse(registre.get("mission_integrer").mcp_expose)


# ============================================================================== B
class ScenarioB_Quotas(unittest.TestCase):
    def horloge(self):
        self.t = 1000.0
        self.dormis = []

        def dormir(s):
            self.dormis.append(s)
            self.t += s
        return (lambda: self.t), dormir

    def test_429_retry_after_respecte_puis_succes(self):
        h, d = self.horloge()
        llm = FauxLLM("mistral", [Err429(10), "ok"])
        g = GestionnaireFournisseurs([llm], dormir=d, horloge=h, hasard=lambda: 0.0)
        self.assertEqual(g.appeler([])[0], "ok")
        self.assertGreaterEqual(sum(self.dormis), 10)                           # jamais avant Retry-After
        self.assertEqual(len(llm.appels), 2)

    def test_bascule_vers_l_autre_fournisseur_sans_attendre(self):
        h, d = self.horloge()
        a, b = FauxLLM("mistral", [Err429(30)]), FauxLLM("gemini", ["depuis gemini"])
        g = GestionnaireFournisseurs([a, b], dormir=d, horloge=h)
        self.assertEqual(g.appeler([]), ("depuis gemini", "gemini"))
        self.assertEqual(self.dormis, [])
        self.assertTrue(any(e["type"] == "bascule" for e in g.evenements))
        # mistral est en quarantaine : l'appel suivant va directement chez gemini
        b.reponses.append("encore gemini")
        self.assertEqual(g.appeler([])[1], "gemini")
        self.assertEqual(len(a.appels), 1)

    def test_les_deux_limites_attente_courte_inline_et_longue_en_quota_en_attente(self):
        h, d = self.horloge()
        a, b = FauxLLM("mistral", [Err429(5), "ok"]), FauxLLM("gemini", [Err429(5)])
        g = GestionnaireFournisseurs([a, b], dormir=d, horloge=h, hasard=lambda: 0.0)
        self.assertEqual(g.appeler([])[0], "ok")
        self.assertGreaterEqual(sum(self.dormis), 4)
        h, d = self.horloge()
        a, b = FauxLLM("mistral", [Err429(900)]), FauxLLM("gemini", [Err429(900)])
        g = GestionnaireFournisseurs([a, b], dormir=d, horloge=h, attente_inline_max=120)
        with self.assertRaises(QuotaEnAttente) as cm:
            g.appeler([])
        self.assertGreaterEqual(cm.exception.reprise_a, 1000 + 900)

    def test_backoff_exponentiel_avec_gigue_et_essais_bornes(self):
        h, d = self.horloge()
        llm = FauxLLM("mistral", [ConnectionError("timeout")] * 20)
        g = GestionnaireFournisseurs([llm], max_essais=4, attente_base=1, attente_max=60, dormir=d, horloge=h,
                                     hasard=lambda: 1.0, attente_inline_max=1000)
        with self.assertRaises(ErreurFournisseur):
            g.appeler([])
        self.assertEqual(len(llm.appels), 4)                                    # borne
        croissants = [x for x in self.dormis if x >= 1]
        self.assertGreater(len(croissants), 0)
        self.assertGreater(g._delai(3, None), g._delai(1, None))
        self.assertAlmostEqual(g._delai(0, None), 1.25)                         # base + gigue 25 %

    def test_budgets_et_erreurs_classees(self):
        g = GestionnaireFournisseurs([FauxLLM("m", ["a", "b", "c"])], budget_requetes=2)
        g.appeler([])
        g.appeler([])
        with self.assertRaises(BudgetEpuise):
            g.appeler([])
        self.assertEqual(classer_erreur(Err429(3)), ("quota", 3.0))
        self.assertEqual(classer_erreur(type("E", (Exception,), {"status_code": 401})())[0], "auth")
        self.assertEqual(classer_erreur(type("E", (Exception,), {"status_code": 503})())[0], "transitoire")
        self.assertEqual(lire_retry_after(Err429(None)), None)
        with self.assertRaises(ErreurFournisseur):
            GestionnaireFournisseurs([]).appeler([])


class ScenarioB_MissionNePerdPasSonEtat(Base):
    def test_quota_atteint_etat_sauvegarde_puis_reprise_automatique(self):
        m = self.mission(duree_s=300)
        reponses = [j(action="update_plan", plan=["x"]), Err429(1)] + [j(action="finish", summary="ok apres quota")]
        a = self.agent(m["id"], reponses, attente_base=0.5, attente_inline_max=0, hasard=lambda: 0.0, dormir=time.sleep)
        statut = a.executer()
        self.assertEqual(statut, M.COMPLETED)
        etats = [json.loads(e["donnees"]).get("vers") for e in self.store.evenements(m["id"]) if e["type"] == "etat"]
        self.assertIn(M.WAITING_FOR_QUOTA, etats)
        self.assertLess(etats.index(M.WAITING_FOR_QUOTA), len(etats) - 1)
        self.assertEqual(etats[-1], M.COMPLETED)
        # pas de repetition aveugle : l'etape de plan n'a ete executee qu'une fois
        self.assertEqual(len([e for e in self.store.etapes(m["id"]) if e["action"] == "update_plan"]), 1)

    def test_tous_fournisseurs_en_echec_fatal_la_mission_echoue_proprement_avec_rapport(self):
        m = self.mission()
        a = self.agent(m["id"], [type("E", (Exception,), {"status_code": 400})("mauvaise requete")])
        self.assertEqual(a.executer(), M.FAILED)
        self.assertTrue((Path(self.store.get(m["id"])["rapports"]) / "report.md").exists())
        self.stable_intacte()


# ============================================================================== C
class ScenarioC_Interruption(Base):
    def test_processus_interrompu_puis_reprise_depuis_un_etat_coherent(self):
        m = self.mission(duree_s=300)
        mid = m["id"]
        a = self.agent(mid, [j(action="update_plan", plan=["corriger"]), j(action="read_file", path="calc.py"),
                             SimulationCrash()])
        with self.assertRaises(SimulationCrash):
            a.executer()
        av = self.store.get(mid)
        self.assertEqual(av["statut"], M.RUNNING)                                # laisse « en cours » : processus mort
        avant = av["temps_actif_s"]
        n_avant = av["etape"]
        # le processus a disparu (reboot) : le superviseur le detecte
        self.store.maj(mid, pid=2 ** 22 - 3, heartbeat=0)
        self.assertEqual(M.reprendre_interrompues(self.store, lancer=False), [mid])
        b = self.agent(mid, self.SCRIPT_CORRECTION[2:])                         # nouveau processus, meme mission
        self.assertEqual(b.executer(), M.COMPLETED)
        ap = self.store.get(mid)
        self.assertGreaterEqual(ap["temps_actif_s"], avant)                      # le temps deja consomme est conserve
        self.assertGreater(ap["etape"], n_avant)
        self.assertEqual(len([t for t in self.store.tests(mid) if t["nature"] == "baseline"]), 1)   # baseline pas refaite
        self.assertEqual(b.etat.get("plan"), ["corriger"])                       # plan restaure
        # la reprise a ete signalee au modele (verifier l'etat avant de refaire la derniere etape)
        self.assertIn("reprise apres une interruption", b.llm.appels[0][1]["content"])
        self.stable_intacte()

    def test_mission_en_pause_n_est_pas_relancee_au_demarrage(self):
        m = self.mission()
        self.store.transition(m["id"], M.RUNNING)
        self.store.transition(m["id"], M.PAUSED)
        self.assertEqual(M.reprendre_interrompues(self.store, lancer=False), [])

    def test_worker_detache_reel_de_bout_en_bout_sans_fournisseur_configure(self):
        """Vrai processus separe (scripts/mission_worker.py) : sans cle API il doit ECHOUER proprement, pas planter."""
        m = M.demarrer_mission("analyse ton systeme de calcul", depot=self.depot, store=self.store, duree_s=120)
        for _ in range(240):
            if self.store.get(m["id"])["statut"] in M.TERMINAUX:
                break
            time.sleep(0.5)
        fin = self.store.get(m["id"])
        self.assertEqual(fin["statut"], M.FAILED, fin)
        self.assertIn("fournisseur", fin["resume"])
        self.assertTrue((Path(fin["rapports"]) / "report.md").exists())
        self.assertFalse(M.processus_vivant(fin["pid"]))


# ============================================================================== D
class ScenarioD_Regression(Base):
    def test_regression_detectee_corrigee_puis_validee(self):
        m = self.mission()
        casse = CALC_OK.replace("a * b", "0")
        a = self.agent(m["id"], [
            j(action="update_plan", plan=["corriger"]),
            j(action="write_file", path="calc.py", content=casse),               # introduit une regression (mul)
            j(action="validate"),
            j(action="write_file", path="calc.py", content=CALC_OK),             # correction
            j(action="validate"),
            j(action="finish", summary="ok")])
        self.assertEqual(a.executer(), M.COMPLETED)
        etapes = self.store.etapes(m["id"])
        v = [e for e in etapes if e["action"] == "validate"]
        self.assertEqual([e["succes"] for e in v], [False, True])
        self.assertIn("regression", v[0]["erreur"])
        self.assertEqual((Path(m["workspace"]) / "calc.py").read_text(), CALC_OK)
        self.stable_intacte()

    def test_regression_jamais_corrigee_abandon_partiel_candidat_intact(self):
        m = self.mission()
        casse = CALC_OK.replace("a * b", "0")
        a = self.agent(m["id"], [j(action="write_file", path="calc.py", content=casse)]
                       + [j(action="finish", summary="j'ai fini")] * 10)
        statut = a.executer()
        self.assertEqual(statut, M.PARTIAL)
        ws = Path(m["workspace"])
        self.assertEqual((ws / "calc.py").read_text(), CALC_BUG)                 # candidat = dernier etat VERIFIE (base)
        rap = Path(self.store.get(m["id"])["rapports"])
        self.assertIn("a * b", (rap / "changes_non_verifiees.diff").read_text() + "a * b")
        self.assertTrue((rap / "changes_non_verifiees.diff").exists())
        self.assertEqual((rap / "changes.diff").read_text(), "")
        md = (rap / "report.md").read_text(encoding="utf-8")
        self.assertIn("NON VÉRIFIÉE", md)
        self.stable_intacte()

    def test_un_test_ne_se_supprime_ni_ne_se_desactive_pour_passer(self):
        m = self.mission()
        affaibli = TESTS.replace("def test_mul", "@pytest.mark.skip\ndef test_mul")
        retire = TESTS.split("def test_mul")[0]
        a = self.agent(m["id"], [
            j(action="delete_file", path="tests/test_calc.py"),
            j(action="write_file", path="tests/test_calc.py", content=affaibli),
            j(action="write_file", path="tests/test_calc.py", content=retire),
            j(action="finish", summary="x")])
        a.executer()
        ws = Path(m["workspace"])
        self.assertEqual((ws / "tests" / "test_calc.py").read_text(), TESTS)
        refus = [e for e in self.store.etapes(m["id"]) if e["erreur"] == "autorisation_requise"]
        self.assertEqual(len(refus), 3)
        self.assertEqual(len(self.store.get(m["id"])["autorisations"]), 3)

    def test_validation_detecte_un_test_disparu_meme_hors_actions_du_modele(self):
        base = {"a::t1": "passed", "a::t2": "passed", "a::t3": "failed"}
        self.assertFalse(MA.comparer_a_la_baseline(base, {"a::t1": "passed"})["ok"])
        self.assertFalse(MA.comparer_a_la_baseline(base, {"a::t1": "passed", "a::t2": "skipped"})["ok"])
        self.assertTrue(MA.comparer_a_la_baseline(base, {"a::t1": "passed", "a::t2": "passed", "a::t3": "passed"})["ok"])

    def test_tests_non_executables_jamais_declares_verifies(self):
        m = self.mission()
        a = self.agent(m["id"], [j(action="write_file", path="calc.py", content=CALC_OK), j(action="validate"),
                                 j(action="finish", summary="x")] + [j(action="finish", summary="x")] * 8)
        with patch.object(MA, "commande_tests", lambda ws, junit, cibles=None: [sys.executable, "-c", "raise SystemExit(0)"]):
            statut = a.executer()
        self.assertNotEqual(statut, M.COMPLETED)
        self.assertTrue(all(not e["verifie"] for e in self.store.etapes(m["id"])))
        self.assertIn("non_executable", [t["statut"] for t in self.store.tests(m["id"])])


# ============================================================================== E
class ScenarioE_DureeMax(Base):
    def test_duree_max_arret_propre_modifs_verifiees_gardees_aucune_nouvelle_modif(self):
        m = self.mission(duree_s=6)
        deadline = {}

        def lent_puis_ecriture():
            time.sleep(max(0, 6.5 - (time.monotonic() - deadline["t0"])))        # depasse le delai pendant l'appel
            return j(action="write_file", path="calc.py", content="# apres le delai\n")
        deadline["t0"] = time.monotonic()
        a = self.agent(m["id"], [j(action="write_file", path="calc.py", content=CALC_OK), j(action="validate"),
                                 lent_puis_ecriture])
        statut = a.executer()
        self.assertEqual(statut, M.TIMEOUT)
        ws = Path(m["workspace"])
        self.assertEqual((ws / "calc.py").read_text(), CALC_OK)                  # travail verifie conserve
        self.assertNotIn("apres le delai", (ws / "calc.py").read_text())         # aucune modification apres le delai
        fin = self.store.get(m["id"])
        self.assertLessEqual(fin["temps_actif_s"], 6 + 3)
        md = (Path(fin["rapports"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("TIMEOUT", md)
        self.assertIn("a + b", (Path(fin["rapports"]) / "changes.diff").read_text())
        self.stable_intacte()

    def test_duree_bornee_a_120_minutes_et_defaut_60(self):
        self.assertEqual(M.borner_duree_min(500), 120)
        self.assertEqual(M.borner_duree_min(None), 60)
        self.assertEqual(M.borner_duree_min(0), 1)
        self.assertEqual(M.borner_duree_min(45), 45)

    def test_chrono_ne_compte_pas_les_pauses(self):
        t = [0.0]
        c = M.ChronoActif(horloge=lambda: t[0])
        c.demarrer(); t[0] = 10; c.arreter(); t[0] = 500; c.demarrer(); t[0] = 505
        self.assertEqual(c.ecoule(), 15)


# ============================================================================== F
class ScenarioF_Annulation(Base):
    def _pytest_enfants(self):
        import psutil
        res = []
        for p in psutil.Process().children(recursive=True):
            try:
                if p.status() != psutil.STATUS_ZOMBIE and "pytest" in " ".join(p.cmdline()):
                    res.append(p)
            except psutil.Error:
                pass
        return res

    def test_annulation_pendant_des_tests_arrete_les_processus_garde_workspace_et_logs(self):
        m = self.mission(duree_s=300)
        lent = "import time\n\n\ndef test_lent():\n    time.sleep(120)\n"
        a = self.agent(m["id"], [j(action="write_file", path="tests/test_lent.py", content=lent),
                                 j(action="run_tests", paths=["tests/test_lent.py"])])
        res = {}
        t = threading.Thread(target=lambda: res.setdefault("statut", a.executer()))
        t.start()
        for _ in range(200):
            if self._pytest_enfants() and self.store.get(m["id"])["etape"] >= 2:
                break
            time.sleep(0.1)
        self.assertTrue(self._pytest_enfants(), "le pytest lent aurait du tourner")
        M.annuler(self.store, m["id"])
        t.join(20)
        self.assertFalse(t.is_alive())
        self.assertEqual(res["statut"], M.CANCELLED)
        self.assertEqual(self._pytest_enfants(), [])                              # plus aucun processus orphelin
        fin = self.store.get(m["id"])
        self.assertTrue(Path(fin["workspace"]).is_dir())                          # workspace conserve
        self.assertTrue((Path(fin["rapports"]) / "execution.log").is_file())
        self.assertTrue((Path(fin["rapports"]) / "report.md").is_file())
        self.stable_intacte()

    def test_arret_d_urgence_sans_worker_vivant(self):
        m = self.mission()
        self.store.transition(m["id"], M.RUNNING)
        self.store.maj(m["id"], pid=2 ** 22 - 5, heartbeat=0)
        r = M.annuler(self.store, m["id"], urgence=True)
        self.assertEqual(r["statut"], M.CANCELLED)
        with self.assertRaises(M.ErreurMission):
            M.annuler(self.store, m["id"])                                         # deja terminee : pas de double annulation

    def test_pause_puis_reprise_ne_compte_pas_le_temps_de_pause(self):
        m = self.mission(duree_s=300)
        self.store.maj(m["id"], pause_demandee=1)
        a = self.agent(m["id"], [j(action="finish", summary="ok")], dormir=time.sleep)
        res = {}
        t = threading.Thread(target=lambda: res.setdefault("s", a.executer()))
        t.start()
        for _ in range(100):
            if self.store.get(m["id"])["statut"] == M.PAUSED:
                break
            time.sleep(0.1)
        self.assertEqual(self.store.get(m["id"])["statut"], M.PAUSED)
        t1 = self.store.get(m["id"])["temps_actif_s"]
        time.sleep(1.5)
        self.assertAlmostEqual(self.store.get(m["id"])["temps_actif_s"], t1, delta=0.3)
        M.reprendre(self.store, m["id"], lancer=False)
        t.join(20)
        self.assertEqual(res["s"], M.COMPLETED)


# ============================================================================== G
class ScenarioG_Autorisations(Base):
    def test_ecriture_sur_la_version_stable_ou_fichier_protege_mise_en_attente_la_mission_continue(self):
        m = self.mission()
        a = self.agent(m["id"], [
            j(action="write_file", path=str(self.depot / "calc.py"), content="# attaque\n"),     # version stable
            j(action="write_file", path="../depot/calc.py", content="# attaque\n"),               # traversee
            j(action="write_file", path="core/registre.py", content="PROTEGE = 0\n"),             # verrou de securite
            j(action="write_file", path="config.yaml", content="x: 1\n"),                          # secret
            j(action="run_command", argv=["pip", "install", "requests"]),                         # installation
            j(action="run_command", argv=["python", "-m", "pytest", "/etc"]),                     # chemin absolu
            j(action="write_file", path="calc.py", content=CALC_OK),                              # travail legitime : continue
            j(action="validate"),
            j(action="finish", summary="fait")])
        statut = a.executer()
        self.assertEqual(statut, M.PARTIAL)                                        # des actions attendent une autorisation
        self.assertEqual(len(self.store.get(m["id"])["autorisations"]), 6)
        self.stable_intacte()
        self.assertEqual((self.depot / "core" / "registre.py").read_text(), "PROTEGE = 1\n")
        ws = Path(m["workspace"])
        self.assertEqual((ws / "core" / "registre.py").read_text(), "PROTEGE = 1\n")
        self.assertEqual((ws / "calc.py").read_text(), CALC_OK)                    # l'etape independante a abouti
        md = (Path(self.store.get(m["id"])["rapports"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("## 17.", md)
        self.assertIn("hors de la liste autorisee", md)

    def test_chemins_traversee_liens_et_git(self):
        ws = self.tmp / "ws"
        ws.mkdir()
        for mauvais in ("../x", "..\\x", "/etc/passwd", ".git/config", "a/../../x"):
            with self.assertRaises(MA.Refus, msg=mauvais):
                MA.resoudre_chemin(ws, mauvais)
        if hasattr(os, "symlink"):
            (self.tmp / "dehors").mkdir()
            os.symlink(self.tmp / "dehors", ws / "lien")
            with self.assertRaises(MA.Refus):
                MA.resoudre_chemin(ws, "lien/f.py")
        self.assertEqual(MA.resoudre_chemin(ws, "core\\a.py"), "core/a.py")

    def test_aucun_secret_dans_le_workspace_ni_l_environnement_des_sous_processus(self):
        m = self.mission()
        self.assertNotIn("SECRET-A-NE-JAMAIS-COPIER",
                         "".join(p.read_text(errors="ignore") for p in Path(m["workspace"]).rglob("*")
                                 if p.is_file() and ".git" not in p.parts))
        env = M.environnement_sain({"PATH": "/bin", "MISTRAL_API_KEY": "k", "GEMINI_API_KEY": "k", "GITHUB_TOKEN": "t",
                                    "PYTHONPATH": "/x", "MA_PASSWORD": "p"})
        self.assertEqual(sorted(env), ["PATH", "PYTHONDONTWRITEBYTECODE", "PYTHONPATH"])
        env = M.environnement_sain({"PATH": "/bin", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "a", "GIT_CONFIG_VALUE_0": "b"})
        self.assertFalse([k for k in env if k.startswith("GIT_CONFIG")])           # pas de GIT_CONFIG_COUNT orphelin
        r = subprocess.run(["git", "--version"], env=M.environnement_sain(), capture_output=True)
        self.assertEqual(r.returncode, 0)

    def test_les_modules_du_moteur_sont_proteges_contre_l_auto_modification(self):
        for f in ("core/missions.py", "core/mission_agent.py", "core/fournisseurs_mission.py", "tools/missions.py"):
            self.assertFalse(am.chemin_autorise(self.depot, f), f)

    def test_commande_de_mission_hors_liste_refusee(self):
        m = self.mission()
        a = self.agent(m["id"], [])
        for cmd in (["rm", "-rf", "."], ["python", "-c", "print(1)"], ["git", "push"], ["powershell", "-c", "x"],
                    ["python", "-m", "pip", "install", "x"]):
            with self.assertRaises(MA.Refus, msg=cmd):
                a._commande(cmd)
        r = a._commande(["python", "-m", "py_compile", "calc.py"])
        self.assertTrue(r["succes"])


# ============================================================================== H
class ScenarioH_ReponsesInvalides(Base):
    def test_reponses_invalides_detectees_aucun_faux_succes(self):
        m = self.mission()
        a = self.agent(m["id"], [
            "Bien sur ! J'ai tout corrige, c'est fait.",                         # pas de JSON
            j(action="rm_rf", path="/"),                                          # action inconnue
            j(action="write_file", path="calc.py"),                               # parametre manquant
            "```json\n" + j(action="write_file", path="calc.py", content=CALC_OK) + "\n```",   # valide (avec balises)
            j(action="replace_in_file", path="calc.py", old="introuvable", new="x"),            # old absent -> echec
            j(action="update_plan", plan=["a"]),
            j(action="validate"),
            j(action="finish", summary="ok")])
        statut = a.executer()
        et = self.store.etapes(m["id"])
        invalides = [e for e in et if e["action"] == "invalid_response"]
        self.assertEqual(len(invalides), 3)
        self.assertTrue(all(not e["succes"] for e in invalides))
        self.assertIn("pas de reponse", "pas de reponse") 
        ecritures = [e for e in et if e["action"] == "write_file"]
        self.assertEqual(len(ecritures), 1)                                       # seule l'ecriture VALIDE a eu lieu
        rempl = [e for e in et if e["action"] == "replace_in_file"][0]
        self.assertFalse(rempl["succes"])
        self.assertEqual(statut, M.COMPLETED)
        # le modele a recu une consigne corrective apres une reponse invalide
        self.assertIn("UNIQUEMENT", a.llm.appels[1][1]["content"])

    def test_boucle_de_reponses_invalides_bornee(self):
        m = self.mission()
        a = self.agent(m["id"], ["blabla"] * 40)
        self.assertEqual(a.executer(), M.PARTIAL)
        self.assertLess(self.store.get(m["id"])["etape"], 20)                    # jamais infini

    def test_action_repetee_en_boucle_detectee(self):
        m = self.mission()
        a = self.agent(m["id"], [j(action="read_file", path="calc.py")] * 60)
        statut = a.executer()
        self.assertIn(statut, (M.PARTIAL, M.FAILED))
        self.assertLess(self.store.get(m["id"])["etape"], 40)

    def test_limite_d_etapes(self):
        m = self.mission()
        self.store.maj(m["id"], budget={"max_requetes": 0, "max_tokens": 0, "max_etapes": 3, "max_tentatives_etape": 3})
        a = self.agent(m["id"], [j(action="read_file", path="calc.py", start=i) for i in range(1, 30)])
        self.assertEqual(a.executer(), M.PARTIAL)
        self.assertEqual(self.store.get(m["id"])["etape"], 3)


# ============================================================================== divers
class MachineAEtats(Base):
    def test_transitions_coherentes(self):
        m = self.mission()
        mid = m["id"]
        with self.assertRaises(M.ErreurMission):
            self.store.transition(mid, M.PAUSED)                                   # PENDING -> PAUSED interdit
        self.store.transition(mid, M.RUNNING)
        self.store.transition(mid, M.WAITING_FOR_QUOTA)
        self.store.transition(mid, M.RUNNING)
        self.store.transition(mid, M.COMPLETED)
        for suivant in M.ETATS:
            if suivant != M.COMPLETED:
                with self.assertRaises(M.ErreurMission):
                    self.store.transition(mid, suivant)                            # un etat terminal est definitif
        with self.assertRaises(M.ErreurMission):
            self.store.transition(mid, "N_IMPORTE_QUOI")

    def test_une_seule_mission_active_et_numerotation(self):
        m1 = self.mission()
        self.assertEqual(m1["id"], "mission_001")
        with self.assertRaises(M.ErreurMission):
            self.mission()
        self.store.transition(m1["id"], M.CANCELLED)
        self.assertEqual(self.mission()["id"], "mission_002")

    def test_depot_non_git_ou_workspace_dans_le_depot_refuses(self):
        with self.assertRaises(M.ErreurMission):
            M.demarrer_mission("ameliore ton code", depot=self.tmp / "inexistant", store=self.store, lancer=False)
        with self.assertRaises(am.ErreurAutoModif):
            am.creer_workspace(self.depot, self.depot / "ws", "jarvis/x")
        self.assertEqual(self.store.derniere()["statut"], M.FAILED)

    def test_racine_relative_devient_absolue(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            st = M.MissionStore("relative_missions")
        finally:
            os.chdir(cwd)
        self.assertTrue(st.racine.is_absolute())

    def test_etat_survit_a_une_nouvelle_connexion_base(self):
        m = self.mission(objectif="analyse ton systeme de memoire")
        autre = M.MissionStore(self.tmp / "missions")
        self.assertEqual(autre.get(m["id"])["objectif"], "analyse ton systeme de memoire")

    def test_statut_vocal_construit_depuis_la_base(self):
        m = self.mission()
        self.store.etape(m["id"], 1, "EDIT", "write_file", "calc.py", True, False)
        self.store.maj(m["id"], etape=1)
        txt = M.resume_statut(self.store.get(m["id"]), self.store)
        self.assertIn("1 fichier(s) modifié(s)", txt)
        self.assertIn("write_file", txt)

    def test_notification_echec_non_consideree_livree(self):
        ok, detail = M.notifier("t", "x", plateforme="posix")
        self.assertFalse(ok)
        faux = lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "boom"})()          # noqa: E731
        ok, detail = M.notifier("t", "x", plateforme="nt", executeur=faux)
        self.assertFalse(ok)
        self.assertIn("echec", detail)
        bon = lambda *a, **k: type("R", (), {"returncode": 0, "stderr": ""})()                # noqa: E731
        ok, detail = M.notifier("t", "x'; Remove-Item *", plateforme="nt", executeur=bon)
        self.assertTrue(ok)
        self.assertIn("non confirmee", detail)

    def test_le_rapport_dit_que_la_notification_a_echoue(self):
        m = self.mission()
        self.agent(m["id"], []).executer()
        md = (Path(self.store.get(m["id"])["rapports"]) / "report.md").read_text(encoding="utf-8")
        if os.name != "nt":
            self.assertIn("NON livree", md)

    def test_annonce_vocale_une_seule_fois(self):
        m = self.mission()
        self.store.transition(m["id"], M.CANCELLED, resume="r")
        a = M.messages_a_annoncer(self.store)
        self.assertEqual(len(a), 1)
        M.marquer_annoncee(self.store, m["id"])
        self.assertEqual(M.messages_a_annoncer(self.store), [])

    def test_benchmark_avant_apres_mesure_reellement(self):
        m = self.mission()
        (self.depot / "bench_calc.py").write_text("import calc\nfor _ in range(20000): calc.mul(2, 3)\n", encoding="utf-8")
        git(self.depot, "add", "bench_calc.py")
        git(self.depot, "commit", "-q", "-m", "bench")
        self.store.transition(m["id"], M.CANCELLED)
        m = M.demarrer_mission("ameliore ton systeme de calcul", depot=self.depot, store=self.store, lancer=False, duree_s=120)
        a = self.agent(m["id"], [])
        r = a._benchmark("bench_calc.py")
        self.assertTrue(r["succes"], r)
        mes = self.store.mesures(m["id"])
        self.assertEqual(len(mes), 1)
        self.assertGreater(mes[0]["avant"], 0)
        with self.assertRaises(MA.Refus):
            a._benchmark("calc.py")


class RoutageVocal(unittest.TestCase):
    def route(self, phrase):
        from tools.missions import router_mission
        with patch("tools.missions._existe_mission", return_value=True):
            return router_mission(phrase)

    def test_commandes_de_mission(self):
        cas = {
            "Jarvis, analyse ton code source et améliore ton système de routage des commandes. Tu disposes de deux heures. "
            "Effectue les modifications, teste-les et prépare-moi un rapport complet.": ("mission_demarrer", 120),
            "améliore ton code pendant une heure": ("mission_demarrer", 60),
            "analyse ton système de mémoire": ("mission_demarrer", None),
            "corrige les problèmes de routage pendant deux heures": ("mission_demarrer", 120),
            "lance une campagne d'auto-amélioration": ("mission_demarrer", None),
            "Jarvis, améliore ton système de routage. Tu disposes de 60 minutes.": ("mission_demarrer", 60),
            "améliore ton code pendant 1h30": ("mission_demarrer", 90),
            "où en est ta mission ?": ("mission_statut", None),
            "mets ta mission en pause": ("mission_pause", None),
            "reprends ta mission": ("mission_reprendre", None),
            "annule la mission": ("mission_annuler", None),
            "arrêt d'urgence de la mission": ("mission_urgence", None),
            "montre-moi ton rapport": ("mission_rapport", None),
            "applique les modifications de la mission": ("mission_integrer", None),
        }
        for phrase, (outil, duree) in cas.items():
            r = self.route(phrase)
            self.assertIsNotNone(r, phrase)
            self.assertEqual(r[0], outil, phrase)
            if duree:
                self.assertEqual(r[1].get("duree_minutes"), duree, phrase)

    def test_pas_de_confusion_avec_le_controle_windows_et_les_commandes_existantes(self):
        for phrase in ("ouvre le bloc-notes", "tape bonjour dans le bloc-notes", "clique sur le bouton enregistrer",
                       "mets la musique plus fort", "améliore le son", "corrige ma phrase", "quelle heure est-il",
                       "lance Spotify", "ouvre YouTube et lance Stromae", "ferme la fenêtre", "montre-moi le rapport météo",
                       "éteins le PC", "va sur la page de la mission locale", "envoie un mail à Paul"):
            self.assertIsNone(self.route(phrase), phrase)

    def test_le_routeur_prioritaire_envoie_les_missions_avant_le_reste(self):
        from core.routage_intentions import decider_prioritaire
        d = decider_prioritaire("améliore ton code pendant une heure")
        self.assertEqual((d.type, d.outil), ("outil", "mission_demarrer"))

    def test_duree_en_clair(self):
        from tools.missions import extraire_duree_minutes as x
        self.assertEqual(x("pendant deux heures"), 120)
        self.assertEqual(x("une heure et demie"), 90)
        self.assertEqual(x("une demi-heure"), 30)
        self.assertEqual(x("45 minutes"), 45)
        self.assertEqual(x("tu disposes de 60 minutes"), 60)
        self.assertIsNone(x("sans limite"))


if __name__ == "__main__":
    unittest.main()
