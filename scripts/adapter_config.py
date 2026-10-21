"""Met ton config.yaml a jour pour les nouvelles fonctions, SANS toucher a tes cles ni a tes reglages.

Usage (a la racine du projet) :  uv run python scripts/adapter_config.py
- sauvegarde config.yaml en config.yaml.bak ;
- vide les cles placeholder (« sk-proj-... », « sk-ant-... ») qui faisaient croire a Jarvis qu'une
  cle OpenAI/Anthropic existait (d'ou l'erreur 401 d'Astra) ;
- ajoute seulement ce qui manque : nom, modeles de vision/secours Mistral, operateur visuel Mistral.
Les commentaires du fichier ne sont pas conserves (la sauvegarde .bak les garde).
"""
import shutil
import sys
from pathlib import Path

import yaml

CHEMIN = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "config.yaml"


def _placeholder(valeur):
    v = str(valeur or "").strip()
    return v.endswith("...") or v in ("sk-proj-...", "sk-ant-...")


def adapter(cfg):
    """Applique les corrections a un dict de config. Renvoie la liste des changements."""
    faits = []

    def regler(chemin, valeur, seulement_si_absent=True):
        cur = cfg
        *cles, dernier = chemin.split(".")
        for c in cles:
            if not isinstance(cur.get(c), dict):
                cur[c] = {}
            cur = cur[c]
        if seulement_si_absent and cur.get(dernier) not in (None, ""):
            return
        cur[dernier] = valeur
        faits.append(f"{chemin} = {valeur!r}")

    for chemin in ("openai.cle", "anthropic.cle"):
        a, b = chemin.split(".")
        if isinstance(cfg.get(a), dict) and _placeholder(cfg[a].get(b)):
            cfg[a][b] = ""
            faits.append(f"{chemin} vidé (placeholder)")
    regler("assistant.nom_utilisateur", "Wafo Arold")
    if str((cfg.get("cloud") or {}).get("fournisseur", "")).lower() == "mistral" or \
            str((cfg.get("mistral") or {}).get("cle", "")).strip():
        regler("astra_pc.fournisseur", "mistral")
        regler("mistral.modele_vision", "pixtral-12b-latest")
        regler("mistral.modeles_vision_secours", ["mistral-small-latest"])
        regler("mistral.modeles_secours", ["ministral-8b-latest", "open-mistral-nemo"])
        regler("stt.modele_mistral", "voxtral-mini-latest")
    regler("navigateur.piloter_avec_chrome", True)
    return faits


def main():
    if not CHEMIN.exists():
        sys.exit(f"{CHEMIN} introuvable : lance ce script depuis la racine du projet.")
    cfg = yaml.safe_load(CHEMIN.read_text(encoding="utf-8")) or {}
    faits = adapter(cfg)
    if not faits:
        print("Rien à changer : ton config.yaml est déjà à jour.")
        return
    shutil.copy2(CHEMIN, CHEMIN.with_suffix(".yaml.bak"))
    CHEMIN.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print("config.yaml mis à jour (sauvegarde : config.yaml.bak) :")
    for f in faits:
        print("  -", f)


if __name__ == "__main__":
    main()
