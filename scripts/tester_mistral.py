"""Diagnostic Mistral : cle, modeles, limites de debit. Usage : uv run python scripts/tester_mistral.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import cloud

client = cloud.client_mistral()
if client is None:
    sys.exit("mistral.cle absente dans config.yaml")
for modele in ("mistral-small-latest", "ministral-8b-latest", "open-mistral-nemo"):
    try:
        brut = client.chat.completions.with_raw_response.create(
            model=modele, max_tokens=5, messages=[{"role": "user", "content": "Dis OK"}])
        h = brut.headers
        lim = {k: v for k, v in h.items() if "ratelimit" in k.lower() or "retry" in k.lower()}
        print(f"[OK ] {modele}: {brut.parse().choices[0].message.content!r} {lim}")
    except Exception as e:
        h = getattr(getattr(e, "response", None), "headers", {}) or {}
        lim = {k: v for k, v in h.items() if "ratelimit" in k.lower() or "retry" in k.lower()}
        print(f"[ERR] {modele}: HTTP {getattr(e, 'status_code', '?')} {str(getattr(e, 'message', e))[:200]} {lim}")
