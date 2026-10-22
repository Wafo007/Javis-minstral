"""Abstraction du modele de langage : le reste du code ignore quel provider tourne.

Trois implementations, choisies par config.yaml :
  - OpenAIProvider : Responses API (cloud recommande, GPT-6 Astra disponible).
  - ClaudeProvider : API Anthropic (repli compatible pour les anciennes configs).
  - OllamaProvider : Ollama en local (http://localhost:11434), 100% offline.

Les deux exposent la meme methode `repondre(systeme, historique, outils)` et
renvoient un objet a la forme d'une reponse Anthropic (.stop_reason + .content,
chaque bloc ayant .type / .text / .name / .input / .id). Ainsi la boucle de
dialogue de jarvis14 ne change pas selon le provider.

L'historique reste au format "content blocks" d'Anthropic ; OllamaProvider le
traduit vers/depuis le format d'Ollama de facon interne.
"""
import json
import logging

# Magasin de certificats Windows (Malwarebytes intercepte le TLS : sans ca, les
# appels a l'API Anthropic echouent en "certificate verify failed").
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

from core.config import reglage
from core import cloud

LOG = logging.getLogger("jarvis")


class Bloc:
    """Bloc interne de Jarvis."""

    def __init__(
        self,
        type,
        text=None,
        id=None,
        name=None,
        input=None,
        extra_content=None
    ):
        self.type = type
        self.text = text
        self.id = id
        self.name = name
        self.input = input
        self.extra_content = extra_content

class Reponse:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


# --------------------------------------------------------------- interface

class ProviderLLM:
    nom = "?"

    def disponible(self):
        return True

    def repondre(self, systeme, historique, outils):
        raise NotImplementedError


# --------------------------------------------------------------- OpenAI (cloud)

class OpenAIProvider(ProviderLLM):
    """Adaptateur Responses API -> forme historique comprise par jarvis14."""

    nom = "OpenAI"

    def __init__(self, modele=None, qualite=False):
        self.modele = modele or cloud.modele(qualite=qualite)
        self.qualite = qualite
        self.client = cloud.client_openai()

    def disponible(self):
        return self.client is not None

    @staticmethod
    def _outils(outils):
        return [{
            "type": "function",
            "name": o["name"],
            "description": o.get("description", ""),
            "parameters": o.get("input_schema", {
                "type": "object", "properties": {}}),
            "strict": False,
        } for o in outils]

    @staticmethod
    def _contenu_image(contenu):
        for item in contenu or []:
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            src = item.get("source", {}) or {}
            if src.get("type") == "base64" and src.get("data"):
                mime = src.get("media_type", "image/jpeg")
                return f"data:{mime};base64,{src['data']}"
        return ""

    def _traduire(self, historique):
        """Historique Anthropic interne -> items Responses API."""
        items = []
        for message in historique:
            role = message.get("role", "user")
            contenu = message.get("content", "")
            if isinstance(contenu, str):
                items.append({"role": role, "content": contenu})
                continue

            if role == "assistant":
                textes = [b.text for b in (contenu or [])
                          if getattr(b, "type", None) == "text" and b.text]
                if textes:
                    items.append({"role": "assistant", "content": " ".join(textes)})
                for bloc in contenu or []:
                    if getattr(bloc, "type", None) != "tool_use":
                        continue
                    items.append({
                        "type": "function_call",
                        "call_id": bloc.id,
                        "name": bloc.name,
                        "arguments": json.dumps(bloc.input or {}, ensure_ascii=False),
                    })
                continue

            # Les resultats d'outils sont des items autonomes. Une capture est
            # ajoutee comme image utilisateur juste apres son function output.
            for resultat in contenu or []:
                if not isinstance(resultat, dict) or resultat.get("type") != "tool_result":
                    continue
                sortie = resultat.get("content", "")
                image = self._contenu_image(sortie) if isinstance(sortie, list) else ""
                items.append({
                    "type": "function_call_output",
                    "call_id": resultat.get("tool_use_id", ""),
                    "output": "Capture d'ecran disponible." if image else str(sortie),
                })
                if image:
                    items.append({"role": "user", "content": [{
                        "type": "input_image", "image_url": image,
                    }]})
        return items

    def repondre(self, systeme, historique, outils):
        kwargs = {
            "model": self.modele,
            "instructions": systeme,
            "input": self._traduire(historique),
            "max_output_tokens": int(reglage("openai.max_output_tokens", 2048)),
            "store": False,
        }
        outils_api = self._outils(outils)
        if outils_api:
            kwargs["tools"] = outils_api
            kwargs["parallel_tool_calls"] = True
        raisonnement = cloud._raisonnement(self.modele, self.qualite)
        if raisonnement:
            kwargs["reasoning"] = raisonnement
        rep = self.client.responses.create(**kwargs)
        cloud.enregistrer_usage(rep, "OpenAI (Jarvis)", self.modele)

        blocs = []
        texte = (getattr(rep, "output_text", "") or "").strip()
        if texte:
            blocs.append(Bloc("text", text=texte))
        for item in getattr(rep, "output", []) or []:
            if getattr(item, "type", None) != "function_call":
                continue
            brut = getattr(item, "arguments", "{}") or "{}"
            try:
                arguments = json.loads(brut) if isinstance(brut, str) else dict(brut)
            except (ValueError, TypeError):
                LOG.warning("OpenAI: arguments outil invalides (%s)", brut)
                arguments = {}
            blocs.append(Bloc(
                "tool_use",
                id=getattr(item, "call_id", None) or getattr(item, "id", None),
                name=getattr(item, "name", ""),
                input=arguments,
            ))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocs) else "end"
        return Reponse(stop, blocs)


# --------------------------------------------------------------- Claude (cloud)

class ClaudeProvider(ProviderLLM):
    nom = "Claude"

    def __init__(self, modele=None):
        import anthropic
        cle = reglage("anthropic.cle", "")
        self.modele = modele or reglage("anthropic.modele", "claude-haiku-4-5")
        self.client = anthropic.Anthropic(api_key=cle) if cle else None

    def disponible(self):
        return self.client is not None

    def repondre(self, systeme, historique, outils):
        # La reponse native Anthropic a deja la bonne forme (.stop_reason/.content).
        kwargs = {
            "model": self.modele,
            "max_tokens": 1024,
            "system": [{"type": "text", "text": systeme,
                        "cache_control": {"type": "ephemeral"}}],
            "messages": historique,
        }
        if outils:
            kwargs["tools"] = outils
        rep = self.client.messages.create(**kwargs)
        # Comptabilite (N9) : tokens + cout estime, par jour, cote Jarvis.
        try:
            u = getattr(rep, "usage", None)
            if u is not None:
                from core import budget
                budget.enregistrer(
                    "Claude (Jarvis)", self.modele,
                    getattr(u, "input_tokens", 0) or 0,
                    getattr(u, "output_tokens", 0) or 0,
                    cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
                    cache_creation=getattr(u, "cache_creation_input_tokens", 0) or 0)
        except Exception:
            pass
        return rep


# --------------------------------------------------------------- Mistral (cloud)

_SECOURS_ANNONCES = set()
_MODELES_BLOQUES = set()   # modeles a 0 requete/minute sur ce compte (ignores le temps de la session)


class MistralProvider(ProviderLLM):
    """Adaptateur Chat Completions Mistral -> forme interne de Jarvis.

    Mistral expose une API Chat Completions compatible avec le SDK OpenAI.
    Jarvis conserve son format interne Anthropic-like pour que la boucle
    d'exécution des outils reste inchangée.
    """

    nom = "Mistral"

    def __init__(self, modele=None, qualite=False):
        self.modele = modele or cloud.modele(qualite=qualite)
        self.qualite = qualite
        self.client = cloud.client_mistral()

    def disponible(self):
        return self.client is not None

    @staticmethod
    def _outils(outils):
        return [{
            "type": "function",
            "function": {
                "name": o["name"],
                "description": o.get("description", ""),
                "parameters": o.get("input_schema", {
                    "type": "object", "properties": {}}),
            },
        } for o in outils]

    @staticmethod
    def _image_data(contenu):
        for item in contenu or []:
            if not isinstance(item, dict) or item.get("type") != "image":
                continue
            src = item.get("source", {}) or {}
            if src.get("type") == "base64" and src.get("data"):
                mime = src.get("media_type", "image/jpeg")
                return f"data:{mime};base64,{src['data']}"
        return ""

    def _traduire(self, systeme, historique):
        messages = [{"role": "system", "content": systeme}]
        for message in historique:
            role = message.get("role", "user")
            contenu = message.get("content", "")
            if isinstance(contenu, str):
                messages.append({"role": role, "content": contenu})
                continue

            if role == "assistant":
                content = []
                tool_calls = []
                for bloc in contenu or []:
                    btype = getattr(bloc, "type", None)
                    if btype == "text" and getattr(bloc, "text", None):
                        content.append({"type": "text", "text": bloc.text})
                    elif btype == "tool_use":
                        tool_calls.append({
                            "id": bloc.id,
                            "type": "function",
                            "function": {
                                "name": bloc.name,
                                "arguments": json.dumps(bloc.input or {}, ensure_ascii=False),
                            },
                        })
                msg = {"role": "assistant", "content": "".join(
                    x["text"] for x in content) if content else None}
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                messages.append(msg)
                continue

            # Les resultats d'outils deviennent des messages role=tool. Une
            # capture d'ecran est ajoutée comme message utilisateur séparé.
            for resultat in contenu or []:
                if not isinstance(resultat, dict) or resultat.get("type") != "tool_result":
                    continue
                sortie = resultat.get("content", "")
                image = self._image_data(sortie) if isinstance(sortie, list) else ""
                messages.append({
                    "role": "tool",
                    "tool_call_id": resultat.get("tool_use_id", ""),
                    "content": "Capture d'ecran disponible." if image else str(sortie),
                })
                if image:
                    messages.append({"role": "user", "content": [{
                        "type": "image_url", "image_url": {"url": image},
                    }]})
        return messages

    def repondre(self, systeme, historique, outils):
        """Mistral principal, Gemini en secours automatique."""

        secours_actif = bool(reglage("cloud.secours_actif", True))
        secours_gemini = reglage("cloud.secours", "gemini") == "gemini"

        def utiliser_gemini():
            print("  [Jarvis] Basculement automatique vers Gemini.")
            return GeminiProvider().repondre(
                systeme, historique, outils
            )

        # Mistral déjà suspendu après une erreur précédente.
        if secours_actif and secours_gemini and not cloud._mistral_disponible():
            return utiliser_gemini()

        if self.client is None:
            if secours_actif and secours_gemini:
                return utiliser_gemini()
            raise RuntimeError("Clé Mistral absente.")

        messages = self._traduire(systeme, historique)

        kwargs = {
            "model": self.modele,
            "messages": messages,
            "max_tokens": int(reglage("mistral.max_tokens", 1024)),
            "temperature": float(reglage("mistral.temperature", 0.3)),
        }

        outils_api = self._outils(outils)

        if outils_api:
            kwargs["tools"] = outils_api
            kwargs["parallel_tool_calls"] = True

        try:
            rep = self.client.chat.completions.create(**kwargs)

        except Exception as e:
            code = getattr(e, "status_code", None)

            if (
                secours_actif
                and secours_gemini
                and code in (403, 429, 500, 502, 503, 504)
            ):
                cloud._suspendre_mistral()
                LOG.warning(
                    "Mistral indisponible (HTTP %s), secours Gemini.",
                    code
                )
                return utiliser_gemini()

            raise

        cloud.enregistrer_usage(
            rep,
            "Mistral (Jarvis)",
            self.modele
        )

        message = rep.choices[0].message
        blocs = []

        texte = (message.content or "").strip()

        if texte:
            blocs.append(Bloc("text", text=texte))

        for tc in (getattr(message, "tool_calls", None) or []):
            brut = getattr(tc.function, "arguments", "{}") or "{}"

            try:
                arguments = (
                    json.loads(brut)
                    if isinstance(brut, str)
                    else dict(brut)
                )
            except (ValueError, TypeError):
                LOG.warning("Mistral: arguments outil invalides")
                arguments = {}

            blocs.append(
                Bloc(
                    "tool_use",
                    id=getattr(tc, "id", None),
                    name=getattr(tc.function, "name", ""),
                    input=arguments,
                    extra_content=getattr(tc, "extra_content", None),
                )
            )

        stop = (
            "tool_use"
            if any(b.type == "tool_use" for b in blocs)
            else "end"
        )

        return Reponse(stop, blocs)


# --------------------------------------------------------------- Gemini (cloud)

class GeminiProvider(MistralProvider):
    """Gemini via l'API OpenAI-compatible.

    Réutilise la traduction des messages et des outils de MistralProvider
    pour préserver le format interne de Jarvis.
    """

    nom = "Gemini"

    def __init__(self, modele=None):
        self.modele = modele or reglage("gemini.modele", "gemini-3.5-flash-lite")
        self.qualite = False
        self.client = cloud.client_gemini()

    def _traduire(self, systeme, historique):
        messages = super()._traduire(systeme, historique)

        for message in messages:
            if message.get("role") != "assistant":
                continue

            appels = message.get("tool_calls") or []

            for appel in appels:
                identifiant = appel.get("id")

                for ancien in historique:
                    if ancien.get("role") != "assistant":
                        continue

                    contenu = ancien.get("content")

                    if not isinstance(contenu, list):
                        continue

                    for bloc in contenu:
                        if (
                            getattr(bloc, "type", None) == "tool_use"
                            and getattr(bloc, "id", None) == identifiant
                        ):
                            extra = getattr(bloc, "extra_content", None)

                            if extra:
                                appel["extra_content"] = extra

        return messages

    def repondre(self, systeme, historique, outils):
        if not self.disponible():
            raise RuntimeError("Gemini n'est pas configuré.")

        kwargs = {
            "model": self.modele,
            "messages": self._traduire(systeme, historique),
            "max_tokens": int(reglage("gemini.max_tokens", 1024)),
        }

        outils_api = self._outils(outils)

        if outils_api:
            kwargs["tools"] = outils_api
            kwargs["tool_choice"] = "auto"

        rep = self.client.chat.completions.create(**kwargs)

        cloud.enregistrer_usage(
            rep,
            "Gemini (Jarvis)",
            self.modele
        )

        message = rep.choices[0].message
        blocs = []

        texte = (message.content or "").strip()

        if texte:
            blocs.append(Bloc("text", text=texte))

        for tc in (getattr(message, "tool_calls", None) or []):
            brut = getattr(tc.function, "arguments", "{}") or "{}"

            try:
                arguments = json.loads(brut) if isinstance(brut, str) else dict(brut)
            except (ValueError, TypeError):
                LOG.warning("Gemini: arguments outil invalides")
                arguments = {}

            blocs.append(
                Bloc(
                    "tool_use",
                    id=getattr(tc, "id", None),
                    name=getattr(tc.function, "name", ""),
                    input=arguments,
                    extra_content=(
                        getattr(tc, "model_extra", None) or {}
                    ).get("extra_content"),
                )
            )

        stop = "tool_use" if any(
            bloc.type == "tool_use" for bloc in blocs
        ) else "end"

        return Reponse(stop, blocs)
# --------------------------------------------------------------- Ollama (local)

class OllamaProvider(ProviderLLM):
    nom = "Ollama"

    def __init__(self):
        self.hote = reglage("ollama.hote", "http://localhost:11434").rstrip("/")
        self.modele = reglage("ollama.modele", "qwen3.5:4b")

    def disponible(self):
        try:
            import requests
            requests.get(f"{self.hote}/api/version", timeout=3)
            return True
        except Exception:
            return False

    # -- traduction historique Anthropic -> messages Ollama --
    def _traduire(self, systeme, historique):
        messages = [{"role": "system", "content": systeme}]
        for m in historique:
            role, contenu = m.get("role"), m.get("content")
            if role == "user":
                if isinstance(contenu, str):
                    messages.append({"role": "user", "content": contenu})
                else:
                    for item in contenu or []:
                        if not isinstance(item, dict):
                            continue
                        if item.get("type") == "tool_result":
                            c = item.get("content")
                            if isinstance(c, list):   # bloc image
                                c = "[image capturee — la vision n'est pas disponible en mode local]"
                            messages.append({"role": "tool", "content": str(c)})
                        elif item.get("type") == "image":
                            messages.append({"role": "user",
                                             "content": "[image — vision indisponible en local]"})
            else:  # assistant
                if isinstance(contenu, str):
                    messages.append({"role": "assistant", "content": contenu})
                else:
                    texte = " ".join(b.text for b in (contenu or [])
                                     if getattr(b, "type", None) == "text" and b.text)
                    appels = [b for b in (contenu or []) if getattr(b, "type", None) == "tool_use"]
                    msg = {"role": "assistant", "content": texte}
                    if appels:
                        msg["tool_calls"] = [
                            {"function": {"name": b.name, "arguments": b.input or {}}}
                            for b in appels]
                    messages.append(msg)
        return messages

    def _outils(self, outils):
        return [{"type": "function", "function": {
            "name": o["name"], "description": o["description"],
            "parameters": o.get("input_schema", {"type": "object", "properties": {}})}}
            for o in outils]

    def _chat(self, messages, tools, nudge=None):
        import requests
        if nudge:
            messages = messages + [{"role": "user", "content": nudge}]
        # think=false : desactive le "raisonnement" natif (qwen3.5, etc.). Sinon le
        # modele est tres lent et rend parfois ses appels d'outils en texte au lieu
        # de les executer. Un modele sans thinking ignore ce parametre.
        corps = {
            "model": self.modele, "messages": messages, "tools": tools,
            "stream": False, "think": bool(reglage("ollama.think", False)),
            "options": {"temperature": 0.3}}
        if not tools:
            corps.pop("tools")
        r = requests.post(f"{self.hote}/api/chat", timeout=120, json=corps)
        r.raise_for_status()
        return r.json()

    def _parser(self, rep):
        msg = rep.get("message", {}) or {}
        blocs = []
        texte = (msg.get("content") or "").strip()
        if texte:
            blocs.append(Bloc("text", text=texte))
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                args = json.loads(args)   # peut lever -> gere par le retry
            blocs.append(Bloc("tool_use", id=f"call_{i}", name=fn.get("name"), input=args or {}))
        stop = "tool_use" if any(b.type == "tool_use" for b in blocs) else "end"
        return Reponse(stop, blocs)

    def repondre(self, systeme, historique, outils):
        messages = self._traduire(systeme, historique)
        tools = self._outils(outils)
        try:
            return self._parser(self._chat(messages, tools))
        except Exception as e:
            LOG.warning("ollama: 1er essai en echec (%s), retry plus directif", e)
            # Retry unique, avec une consigne plus stricte sur l'appel d'outil.
            nudge = ("Rappel : pour agir, appelle l'outil approprie via un tool call "
                     "avec des arguments JSON valides ; sinon reponds simplement en texte.")
            try:
                return self._parser(self._chat(messages, tools, nudge=nudge))
            except Exception:
                LOG.exception("ollama: echec apres retry")
                return Reponse("end", [Bloc("text", text=(
                    "Desole, le modele local n'a pas reussi a traiter la demande "
                    "correctement. Reessaie en reformulant, ou repasse en mode cloud."))])


# --------------------------------------------------------------- fabrique

_LLM = None


def llm():
    """Provider LLM courant selon le mode (local | hybride | qualite).

    - local   : Ollama.
    - hybride : cloud economique (OpenAI par defaut) - reflexes + vision.
    - qualite : cloud fort (GPT-6 Astra par defaut)."""
    global _LLM
    if _LLM is None:
        from core.routage import mode_actuel
        m = mode_actuel()
        if m == "local":
            _LLM = OllamaProvider()
        else:
            qualite = m == "qualite"
            fournisseur = cloud.fournisseur()
            if fournisseur == "openai":
                _LLM = OpenAIProvider(cloud.modele(qualite=qualite), qualite=qualite)
            elif fournisseur == "mistral":
                _LLM = MistralProvider(
                    cloud.modele(qualite=qualite),
                    qualite=qualite
                )
            elif fournisseur == "gemini":
                _LLM = GeminiProvider()
            else:
                _LLM = ClaudeProvider(
                    cloud.modele(qualite=qualite)
                )
        LOG.info("provider LLM : %s (mode %s, modele %s)",
                 _LLM.nom, m, getattr(_LLM, "modele", "-"))
    return _LLM


def reinitialiser():
    """Force la reconstruction du provider au prochain llm() (apres un switch de mode)."""
    global _LLM
    _LLM = None
