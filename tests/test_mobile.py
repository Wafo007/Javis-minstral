"""Controle du telephone Android par ADB : analyses de sorties, pilote, outils, permissions, routage vocal.

DOUBLURE : aucun vrai telephone ni vrai adb ici. ``FauxTelephone`` rejoue des sorties types de ``dumpsys`` & co.
Ces tests valident la logique du PC (analyse, protection des arguments, verification, permissions) ; le comportement
reel d'un Tecno/HiOS sous Android 12 reste a valider avec le vrai appareil (docs/mobile_android.md).
"""
import shlex
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import mobile_adb as MB
from core import registre

registre.charger_outils()

BATTERIE = """Current Battery Service state:
  AC powered: false
  USB powered: true
  status: 2
  level: 87
  temperature: 312
"""
FOCUS = "  mCurrentFocus=Window{4f3a1b2 u0 com.whatsapp/com.whatsapp.HomeActivity}\n"
POWER = "  mWakefulness=Awake\n"
NOTIFS = """  NotificationRecord(0x0a1b: pkg=com.whatsapp user=UserHandle{0} id=1 tag=null importance=3)
    extras={
      android.title=String (Paul)
      android.text=SpannableString (Tu viens ce soir ?)
    }
  NotificationRecord(0x0c2d: pkg=com.google.android.gm user=UserHandle{0} id=2 tag=null importance=3)
      android.title=Facture
      android.text=Votre facture est disponible
  NotificationRecord(0x0e3f: pkg=android user=UserHandle{0} id=3 tag=null importance=1)
      android.progress=0
"""
UI = ('Some noise\n<?xml version=\'1.0\' encoding=\'UTF-8\' standalone=\'yes\' ?><hierarchy rotation="0">'
      '<node text="" content-desc="" package="com.whatsapp" clickable="false" bounds="[0,0][720,1600]">'
      '<node text="Envoyer" content-desc="" package="com.whatsapp" clickable="true" bounds="[600,1400][700,1500]"/>'
      '<node text="" content-desc="Joindre" package="com.whatsapp" clickable="true" bounds="[10,1400][110,1500]"/>'
      '<node text="Paul" content-desc="" package="com.whatsapp" clickable="false" bounds="[0,100][300,200]"/>'
      '</node></hierarchy>UI hierarchy dumped to: /dev/tty')
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PACKAGES = "package:com.whatsapp\npackage:com.tecno.camera\npackage:com.zhiliaoapp.musically\npackage:fr.banque.app\n"


class FauxTelephone:
    """Remplace subprocess.run : memorise les commandes et repond selon le contenu de la ligne `shell`."""

    def __init__(self):
        self.appels = []
        self.devices = "List of devices attached\nSERIE123\tdevice\n"
        self.focus = FOCUS
        self.dcim = ["IMG_001.jpg"]
        self.ui = UI
        self.monkey = "Events injected: 1\n"
        self.connect_out = "connected to 192.0.2.5:5555\n"

    def __call__(self, cmd, capture_output=True, timeout=None):
        self.appels.append(cmd)
        out, err, rc = "", "", 0
        args = cmd[1:]
        if args[0] == "-s":
            args = args[2:]
        if args[0] == "devices":
            out = self.devices
        elif args[0] == "connect":
            out = self.connect_out
        elif args[0] == "pair":
            out = "Successfully paired to 192.0.2.5:37000 [guid=adb-X]\n" if args[2] == "123456" else "Failed: wrong code\n"
        elif args[0] == "exec-out" and args[1] == "uiautomator":
            out = self.ui
        elif args[0] == "exec-out" and args[1] == "screencap":
            out = PNG
        elif args[0] == "pull":
            Path(args[2]).write_bytes(b"JPEG")
        elif args[0] == "shell":
            ligne = args[1]
            if ligne.startswith("dumpsys battery"):
                out = BATTERIE
            elif ligne.startswith("dumpsys power"):
                out = POWER
            elif ligne.startswith("dumpsys window"):
                out = self.focus
            elif ligne.startswith("dumpsys notification"):
                out = NOTIFS
            elif ligne.startswith("dumpsys wifi"):
                out = "mWifiInfo SSID: x, rssi=-58, Link speed: 72Mbps"
            elif ligne.startswith("dumpsys telephony.registry"):
                out = "mSignalStrength=SignalStrength: level=3 asu=20"
            elif ligne.startswith("dumpsys location"):
                out = "  last location=Location[fused 6.37250,2.39830 hAcc=18.0 et=+1h2m]\n"
            elif ligne.startswith("getprop ro.product.model"):
                out = "TECNO BF7\n"
            elif ligne.startswith("getprop ro.build.version.release"):
                out = "12\n"
            elif ligne.startswith("pm list packages"):
                out = PACKAGES
            elif ligne.startswith("monkey"):
                out = self.monkey
            elif ligne.startswith("ls -t"):
                out = "\n".join(self.dcim)
            elif ligne.startswith("wm size"):
                out = "Physical size: 720x1640\n"
            elif ligne.startswith("input keyevent 27"):
                self.dcim.insert(0, "IMG_002.jpg")
        return SimpleNamespace(returncode=rc, stdout=out.encode() if isinstance(out, str) else out, stderr=err.encode())

    def shell_lignes(self):
        return [c[-1] for c in self.appels if "shell" in c]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tel = FauxTelephone()
        self.adb = MB.Adb(adb="adb", appareil="", runner=self.tel, dormir=lambda s: None, dossier=self.tmp)


class AnalysesPures(unittest.TestCase):
    def test_batterie_focus_ecran_position_signal(self):
        b = MB.parser_batterie(BATTERIE)
        self.assertEqual((b["niveau"], b["en_charge"], b["temperature_c"]), (87, True, 31.2))
        self.assertEqual(MB.parser_focus(FOCUS), "com.whatsapp")
        self.assertEqual(MB.parser_focus("  mResumedActivity: ActivityRecord{1 u0 com.android.chrome/org.x.Main t5}"),
                         "com.android.chrome")
        self.assertEqual(MB.parser_focus("rien"), "")
        self.assertTrue(MB.parser_ecran_allume(POWER))
        self.assertFalse(MB.parser_ecran_allume("mWakefulness=Asleep"))
        self.assertIsNone(MB.parser_ecran_allume("?"))
        p = MB.parser_position("last location=Location[fused 6.37250,2.39830 hAcc=18.0]")
        self.assertEqual((p["latitude"], p["longitude"], p["precision_m"]), (6.3725, 2.3983, 18.0))
        self.assertIsNone(MB.parser_position("pas de position"))
        self.assertEqual(MB.parser_signal("rssi=-58 level=3 ")["wifi_rssi_dbm"], -58)

    def test_notifications_formats_android12(self):
        n = MB.parser_notifications(NOTIFS)
        self.assertEqual(len(n), 2)                                                 # la 3e n'a ni titre ni texte
        self.assertEqual(n[0], {"paquet": "com.whatsapp", "titre": "Paul", "texte": "Tu viens ce soir ?"})
        self.assertEqual(n[1]["titre"], "Facture")

    def test_interface_et_recherche_d_element(self):
        els = MB.parser_ui(UI)
        self.assertEqual(MB.trouver_element(els, "envoyer")["x"], 650)
        self.assertEqual(MB.trouver_element(els, "joindre")["desc"], "Joindre")     # via content-desc
        self.assertIsNone(MB.trouver_element(els, "inexistant"))
        self.assertEqual(MB.parser_ui("pas de xml"), [])

    def test_resolution_des_noms_d_application(self):
        self.assertEqual(MB.trouver_paquet("", "WhatsApp"), "com.whatsapp")
        self.assertEqual(MB.trouver_paquet(PACKAGES, "la camera"), "com.tecno.camera")
        self.assertEqual(MB.trouver_paquet(PACKAGES, "tiktok"), "com.zhiliaoapp.musically")
        self.assertEqual(MB.trouver_paquet(PACKAGES, "ma banque", {"ma banque": "fr.banque.app"}), "fr.banque.app")
        self.assertEqual(MB.trouver_paquet(PACKAGES, "x; rm -rf /"), "")
        self.assertEqual(MB.trouver_paquet(PACKAGES, "fr.banque.app"), "fr.banque.app")


class Pilote(Base):
    def test_statut(self):
        s = self.adb.statut()
        self.assertEqual((s["modele"], s["android"], s["niveau"], s["en_charge"], s["ecran_allume"]),
                         ("TECNO BF7", "12", 87, True, True))
        self.assertEqual(s["app_au_premier_plan"], "com.whatsapp")
        self.assertEqual(s["signal"]["wifi_rssi_dbm"], -58)

    def test_lancer_app_verifiee_par_le_premier_plan(self):
        r = self.adb.lancer_app("WhatsApp")
        self.assertEqual((r["paquet"], r["verifie"]), ("com.whatsapp", True))
        self.assertTrue(any(l.startswith("monkey -p com.whatsapp") for l in self.tel.shell_lignes()))
        self.tel.focus = "mCurrentFocus=Window{1 u0 com.android.launcher/x.Y}"
        self.assertFalse(self.adb.lancer_app("WhatsApp")["verifie"])               # lancee mais NON constatee

    def test_app_inconnue_ou_non_installee(self):
        with self.assertRaises(MB.ErreurMobile):
            self.adb.lancer_app("application qui n'existe pas")
        self.tel.monkey = "** No activities found to run, monkey aborted.\n"
        with self.assertRaises(MB.ErreurMobile):
            self.adb.lancer_app("whatsapp")

    def test_aucune_injection_cote_telephone(self):
        self.adb.taper_texte("bonjour; reboot")
        ligne = [l for l in self.tel.shell_lignes() if l.startswith("input text")][0]
        self.assertEqual(shlex.split(ligne), ["input", "text", "bonjour;%sreboot"])    # ';' reste un caractere, pas une commande
        with self.assertRaises(MB.ErreurMobile):
            self.adb.taper_texte("accentué")
        with self.assertRaises(MB.ErreurMobile):
            self.adb.taper_texte("deux\nlignes")
        with self.assertRaises(MB.ErreurMobile):
            self.adb.ouvrir_url("javascript:alert(1)")
        self.adb.ouvrir_url("https://exemple.org/a?b=1&c=2")
        ligne = [l for l in self.tel.shell_lignes() if l.startswith("am start")][0]
        self.assertIn("'https://exemple.org/a?b=1&c=2'", ligne)

    def test_touches_media_defilement(self):
        self.adb.touche("retour")
        self.adb.media("pause")
        self.adb.media("suivant")
        self.adb.defiler("bas")
        lignes = self.tel.shell_lignes()
        self.assertIn("input keyevent 4", lignes)
        self.assertIn("input keyevent 85", lignes)
        self.assertIn("input keyevent 87", lignes)
        self.assertTrue(any(l.startswith("input swipe 360 1148 360 492") for l in lignes))      # ecran 720x1640
        with self.assertRaises(MB.ErreurMobile):
            self.adb.touche("detruire")
        with self.assertRaises(MB.ErreurMobile):
            self.adb.defiler("diagonale")

    def test_toucher_texte_et_verification_du_changement(self):
        r = self.adb.toucher_texte("Envoyer")
        self.assertEqual((r["x"], r["y"]), (650, 1450))
        self.assertFalse(r["verifie"])                                            # l'ecran n'a pas change : on ne pretend pas
        self.assertIn("input tap 650 1450", self.tel.shell_lignes())
        with self.assertRaises(MB.ErreurMobile):
            self.adb.toucher_texte("Bouton fantome")

    def test_capture_photo_notifications_position(self):
        f = self.adb.capture_ecran()
        self.assertTrue(f.exists() and f.read_bytes().startswith(b"\x89PNG"))
        photo = self.adb.photo()
        self.assertTrue(photo.exists())
        self.assertIn("IMG_002.jpg", photo.name)
        self.assertEqual(self.adb.notifications()[0]["paquet"], "com.whatsapp")
        self.assertEqual(self.adb.position()["latitude"], 6.3725)
        self.adb.notification("Titre", "Message ; avec ' guillemet")
        ligne = [l for l in self.tel.shell_lignes() if l.startswith("cmd notification post")][0]
        self.assertEqual(shlex.split(ligne)[-1], "Message ; avec ' guillemet")

    def test_photo_non_constatee_n_est_pas_declaree(self):
        with patch.object(self.tel, "dcim", ["IMG_001.jpg"]), patch.object(MB.Adb, "shell", autospec=True) as sh:
            sh.side_effect = lambda s, *a, **k: "IMG_001.jpg" if a[0] == "ls" else ""
            with self.assertRaises(MB.ErreurMobile):
                self.adb.photo()

    def test_connexion_erreurs_lisibles(self):
        self.tel.devices = "List of devices attached\n"
        with self.assertRaises(MB.ErreurMobile) as cm:
            self.adb.statut()
        self.assertIn("debogage sans fil", str(cm.exception))
        self.tel.devices = "List of devices attached\nSERIE123\tunauthorized\n"
        a = MB.Adb(adb="adb", appareil="SERIE123", runner=self.tel, dormir=lambda s: None)
        with self.assertRaises(MB.ErreurMobile):
            a.statut()
        with self.assertRaises(MB.ErreurMobile):
            self.adb.connecter("pas une adresse; rm")
        self.assertIn("connected", self.adb.connecter("192.0.2.5:5555"))
        self.assertEqual(self.adb.appareil, "192.0.2.5:5555")
        self.assertIn("paired", self.adb.appairer("192.0.2.5:37000", "123456").lower())
        with self.assertRaises(MB.ErreurMobile):
            self.adb.appairer("192.0.2.5:37000", "000000")
        with self.assertRaises(MB.ErreurMobile):
            self.adb.appairer("192.0.2.5:37000", "abc")

    def test_reconnexion_automatique_sur_l_adresse_configuree(self):
        etats = ["List of devices attached\n", "List of devices attached\n192.0.2.5:5555\tdevice\n"]
        tel = self.tel
        tel.devices = etats[0]
        orig = tel.__call__

        def run(cmd, **kw):
            if "connect" in cmd:
                tel.devices = etats[1]
            return orig(cmd, **kw)
        a = MB.Adb(adb="adb", appareil="192.0.2.5:5555", runner=run, dormir=lambda s: None)
        a.assurer_connexion()
        self.assertTrue(any("connect" in c for c in tel.appels))

    def test_adb_absent(self):
        def absent(*a, **k):
            raise FileNotFoundError()
        with self.assertRaises(MB.ErreurMobile) as cm:
            MB.Adb(runner=absent).appareils()
        self.assertIn("platform-tools", str(cm.exception))


class Outils(Base):
    def setUp(self):
        super().setUp()
        from tools import mobile
        self.m = mobile
        p = patch.object(mobile, "_adb", lambda: self.adb)
        p.start()
        self.addCleanup(p.stop)

    def test_niveaux_de_permission_et_non_exposition(self):
        n1 = ["mobile_statut", "mobile_lancer_application", "mobile_ouvrir_url", "mobile_touche", "mobile_lire_media",
              "mobile_defiler", "mobile_envoyer_notification"]
        n2 = ["mobile_toucher", "mobile_taper_texte", "mobile_lire_ecran", "mobile_capture_ecran",
              "mobile_lire_notifications", "mobile_position", "mobile_photo"]
        for nom in n1:
            self.assertEqual(registre.niveau(nom), "N1", nom)
        for nom in n2:
            self.assertEqual(registre.niveau(nom), "N2", nom)
            self.assertTrue(registre.get(nom).confirmation, nom)
        for nom in n1 + n2:
            self.assertFalse(registre.get(nom).mcp_expose, nom)                      # jamais au MCP / pont iPhone / Hermes

    def test_outils_resultats_structures(self):
        r = self.m.mobile_statut()
        self.assertTrue(r.succes and r.verifie)
        self.assertIn("batterie 87 %", r)
        r = self.m.mobile_lancer_application("whatsapp")
        self.assertTrue(r.succes and r.verifie)
        r = self.m.mobile_lire_notifications()
        self.assertIn("Paul", r)
        r = self.m.mobile_photo()
        self.assertTrue(r.verifie and Path(r.details["chemin"]).exists())
        self.assertFalse(self.m.mobile_touche("retour").verifie)                    # envoye != constate

    def test_erreurs_deviennent_des_reponses_parlees(self):
        self.tel.devices = "List of devices attached\n"
        r = self.m.mobile_statut()
        self.assertFalse(r.succes)
        self.assertIn("debogage sans fil", r)
        r = self.m.mobile_lancer_application("zzz introuvable")
        self.assertFalse(r.succes)

    def test_toucher_sans_cible(self):
        self.assertFalse(self.m.mobile_toucher().succes)


class Routage(unittest.TestCase):
    def r(self, phrase):
        from tools.mobile import router_mobile
        return router_mobile(phrase)

    def test_phrases_visant_le_telephone(self):
        cas = {
            "lance WhatsApp sur mon téléphone": ("mobile_lancer_application", {"nom": "whatsapp"}),
            "ouvre YouTube sur mon portable": ("mobile_lancer_application", {"nom": "youtube"}),
            "quelle est la batterie de mon téléphone ?": ("mobile_statut", {}),
            "lis les notifications de mon téléphone": ("mobile_lire_notifications", {}),
            "prends une photo avec mon téléphone": ("mobile_photo", {}),
            "fais une capture d'écran de mon téléphone": ("mobile_capture_ecran", {}),
            "mets pause sur mon téléphone": ("mobile_lire_media", {"action": "pause"}),
            "musique suivante sur mon téléphone": ("mobile_lire_media", {"action": "suivant"}),
            "monte le volume de mon téléphone": ("mobile_lire_media", {"action": "volume_plus"}),
            "retour sur mon téléphone": ("mobile_touche", {"touche": "retour"}),
            "où est mon téléphone": ("mobile_position", {}),
        }
        for phrase, attendu in cas.items():
            self.assertEqual(self.r(phrase), attendu, phrase)

    def test_sans_indice_telephone_rien_n_est_capte(self):
        for phrase in ("lance WhatsApp", "ouvre YouTube", "mets pause", "monte le volume", "quelle est la batterie du PC",
                       "prends une photo", "prends une capture d'écran", "lis mes notifications", "ouvre le bloc-notes",
                       "appelle mon portable pour confirmer"):
            self.assertIsNone(self.r(phrase), phrase)

    def test_priorite_sur_l_ouverture_d_application_du_pc(self):
        from core.routage_intentions import decider_prioritaire
        d = decider_prioritaire("lance WhatsApp sur mon téléphone")
        self.assertEqual((d.type, d.outil), ("outil", "mobile_lancer_application"))
        d2 = decider_prioritaire("lance WhatsApp")
        self.assertNotEqual(d2.outil if d2 else "", "mobile_lancer_application")      # PC inchange (retro-compatibilite)

    def test_domaine_du_catalogue_llm(self):
        from core.routage_intentions import modules_pour_phrase
        self.assertIn("mobile", modules_pour_phrase("fais défiler l'écran de mon téléphone vers le bas"))


if __name__ == "__main__":
    unittest.main()
