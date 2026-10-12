"""Profils de voix : lister, choisir (feminine, masculine, francaise, X), revenir en arriere.

Sources de voix reellement presentes :
  * profils de config.yaml (tts.profils) : aucun identifiant n'est invente, tu les fournis ;
  * voix Windows SAPI installees (detectees automatiquement) ;
  * voix ElevenLabs du compte (si une cle valide est configuree).
Config :
  tts:
    voix_defaut: jarvis            # profil utilise par defaut (optionnel)
    profils:
      jarvis: {moteur: elevenlabs, voix: "<voice_id>", genre: m, langue: fr}
      douce:  {moteur: windows, sapi_voix: "Microsoft Hortense Desktop", genre: f, langue: fr}
      locale: {moteur: piper, modele: "C:/.../fr_FR.onnx", genre: f, langue: fr}
Les modes (nuit...) peuvent pointer un profil : modes_usage.nuit.voix: douce.
"""
from __future__ import annotations

import json
import subprocess
import unicodedata
from pathlib import Path

try:
    from core.config import reglage as _reglage
except Exception:
    def _reglage(chemin, defaut=None):
        return defaut

FICHIER = Path(__file__).resolve().parent.parent / "notes" / ".voix_profil.json"
_SAPI = {"liste": None}
_EL = {"liste": None}


def _sa(s):
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def _etat():
    try:
        return json.loads(FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _sauver(etat):
    try:
        FICHIER.parent.mkdir(parents=True, exist_ok=True)
        FICHIER.write_text(json.dumps(etat, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------ sources de voix
def voix_sapi():
    """Voix Windows installees : [{nom, genre, langue}] (vide hors Windows)."""
    if _SAPI["liste"] is None:
        out = []
        try:
            script = ("Add-Type -AssemblyName System.Speech; "
                      "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() | "
                      "ForEach-Object { $_.VoiceInfo } | "
                      "Select-Object Name,Gender,@{n='Culture';e={$_.Culture.Name}} | ConvertTo-Json -Compress")
            r = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True,
                               timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            brut = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
            for v in (brut if isinstance(brut, list) else [brut]):
                out.append({"nom": v["Name"], "genre": "f" if str(v.get("Gender")).lower().startswith("f") else "m",
                            "langue": str(v.get("Culture", ""))[:2].lower()})
        except Exception:
            pass
        _SAPI["liste"] = out
    return _SAPI["liste"]


def voix_elevenlabs():
    cle = _reglage("elevenlabs.cle", "")
    if not cle:
        return []
    if _EL["liste"] is None:
        out = []
        try:
            import urllib.request
            req = urllib.request.Request("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": cle})
            with urllib.request.urlopen(req, timeout=5) as r:
                for v in json.loads(r.read().decode("utf-8")).get("voices", []):
                    lab = v.get("labels") or {}
                    g = str(lab.get("gender", "")).lower()
                    out.append({"nom": v["name"], "id": v["voice_id"],
                                "genre": "f" if g.startswith("f") else "m" if g.startswith("m") else None})
        except Exception:
            pass
        _EL["liste"] = out
    return _EL["liste"]


def profils_disponibles(avec_cloud=True):
    """{nom: profil}. Les profils de config passent en premier."""
    res = {}
    conf = _reglage("tts.profils", None)
    if isinstance(conf, dict):
        for nom, p in conf.items():
            if isinstance(p, dict):
                res[str(nom)] = {"nom": str(nom), "moteur": str(p.get("moteur", "windows")).lower(),
                                 "genre": (str(p.get("genre", ""))[:1].lower() or None),
                                 "langue": (str(p.get("langue", "fr"))[:2].lower() or None),
                                 "voix": p.get("voix"), "modele": p.get("modele"),
                                 "voix_nom": p.get("voix_nom"), "sapi_voix": p.get("sapi_voix"),
                                 "vitesse": p.get("vitesse"), "source": "config"}
    for v in voix_sapi():
        court = v["nom"].replace("Microsoft ", "").replace(" Desktop", "")
        res.setdefault(court, {"nom": court, "moteur": "windows", "genre": v["genre"], "langue": v["langue"],
                               "sapi_voix": v["nom"], "source": "windows"})
    if avec_cloud:
        for v in voix_elevenlabs():
            res.setdefault(v["nom"], {"nom": v["nom"], "moteur": "elevenlabs", "genre": v["genre"],
                                      "langue": None, "voix": v["id"], "source": "elevenlabs"})
    return res


# ------------------------------------------------------------ choix
_GENRE = {"feminine": "f", "feminin": "f", "femme": "f", "femelle": "f",
          "masculine": "m", "masculin": "m", "homme": "m", "male": "m"}
_LANGUE = {"francaise": "fr", "francais": "fr", "anglaise": "en", "anglais": "en", "english": "en",
           "espagnole": "es", "espagnol": "es", "allemande": "de", "allemand": "de"}


def resoudre(critere, profils=None):
    """Nom du profil correspondant a « feminine », « francaise », « douce »... ou None."""
    profils = profils if profils is not None else profils_disponibles()
    c = _sa(critere).replace("voix", " ").replace("la ", " ").replace("le ", " ").strip()
    mots = [m for m in c.replace("'", " ").split() if m not in ("de", "du", "une", "un", "d", "l")]
    if not mots or not profils:
        return None
    for nom in profils:                                           # nom exact / contenu
        if _sa(nom) == c or (_sa(nom) in c and len(_sa(nom)) > 2):
            return nom
    genre = next((_GENRE[m] for m in mots if m in _GENRE), None)
    langue = next((_LANGUE[m] for m in mots if m in _LANGUE), None)
    if genre or langue:
        for nom, p in profils.items():
            if (not genre or p.get("genre") == genre) and (not langue or p.get("langue") == langue):
                return nom
        return None
    if "naturelle" in mots or "naturel" in mots:
        return next((n for n, p in profils.items() if p["moteur"] != "windows"), None)
    if any(m in ("defaut", "principale", "habituelle", "normale") for m in mots):
        defaut = _reglage("tts.voix_defaut", None)
        return defaut if defaut in profils else next(iter(profils), None)
    return next((n for n in profils if any(m in _sa(n) for m in mots if len(m) > 2)), None)


def _valeurs_tts(p):
    v = {"tts.moteur": p["moteur"], "tts.vitesse": p.get("vitesse")}
    if p["moteur"] == "elevenlabs":
        v["elevenlabs.voix"] = p.get("voix")
    elif p["moteur"] == "piper":
        v["piper.modele"] = p.get("modele")
    elif p["moteur"] == "kokoro":
        v["kokoro.voix_nom"] = p.get("voix_nom") or p.get("voix")
    else:
        v["sapi.voix"] = p.get("sapi_voix")
        v["sapi.genre"] = p.get("genre")
    return v


def appliquer(nom, profils=None):
    """Active un profil (provider reconstruit). Renvoie True si applique."""
    profils = profils if profils is not None else profils_disponibles(avec_cloud=False)
    p = profils.get(nom)
    if not p:
        return False
    try:
        from core import tts as _tts
        _tts.surcharger(_valeurs_tts(p))
    except Exception:
        return False
    return True


def selection_sapi():
    """(nom_voix, genre) a utiliser par la voix Windows, selon le profil actif."""
    try:
        from core import tts as _tts
        return _tts._reg("sapi.voix", None), _tts._reg("sapi.genre", None)
    except Exception:
        return None, None


def utiliser(critere):
    profils = profils_disponibles()
    nom = resoudre(critere, profils)
    if nom is None:
        return f"Je n'ai pas de voix « {critere.strip()} ». {liste_texte(profils)}"
    etat = _etat()
    if etat.get("courant") != nom:
        etat["precedent"] = etat.get("courant")
    etat["courant"] = nom
    if not appliquer(nom, profils):
        return "Je n'ai pas réussi à activer cette voix."
    _sauver(etat)
    return f"Voix {nom} activée."


def precedente():
    etat = _etat()
    ancien = etat.get("precedent")
    if not ancien:
        return "Je n'ai pas de voix précédente en mémoire."
    etat["precedent"], etat["courant"] = etat.get("courant"), ancien
    if not appliquer(ancien, profils_disponibles()):
        return "Je n'ai pas réussi à revenir à la voix précédente."
    _sauver(etat)
    return f"Retour à la voix {ancien}."


def restaurer():
    """Au demarrage : retrouve la voix choisie la derniere fois (sans reseau)."""
    nom = _etat().get("courant") or _reglage("tts.voix_defaut", None)
    if nom:
        appliquer(nom, profils_disponibles(avec_cloud=False))


def appliquer_pour_mode(nom_profil):
    """Voix liee a un mode (ex. nuit -> « douce ») ; si absente, on garde la voix choisie."""
    profils = profils_disponibles(avec_cloud=False)
    cible = nom_profil if nom_profil in profils else (_etat().get("courant") or _reglage("tts.voix_defaut", None))
    if cible in profils:
        appliquer(cible, profils)


def liste_texte(profils=None):
    profils = profils if profils is not None else profils_disponibles()
    if not profils:
        return "Aucune voix configurée. Ajoute des profils dans tts.profils de config.yaml."
    etiq = {"f": "féminine", "m": "masculine"}
    morceaux = []
    for nom, p in list(profils.items())[:8]:
        details = ", ".join(x for x in (etiq.get(p.get("genre")), "française" if p.get("langue") == "fr" else
                                        "anglaise" if p.get("langue") == "en" else None) if x)
        morceaux.append(f"{nom}" + (f" ({details})" if details else ""))
    reste = len(profils) - 8
    return "Voix disponibles : " + ", ".join(morceaux) + (f" et {reste} autres" if reste > 0 else "") + \
        ". Dites « utilise la voix » suivie du nom."
