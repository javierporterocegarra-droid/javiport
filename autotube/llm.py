"""Cliente de Claude: llamadas con salida JSON estructurada e investigación con búsqueda web."""

import json
import logging

import anthropic

log = logging.getLogger(__name__)

# Si un clasificador de seguridad rechaza la petición, la API la reintenta
# automáticamente en un modelo de respaldo dentro de la misma llamada.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self, cfg: dict):
        self.client = anthropic.Anthropic(max_retries=4)
        self.model = cfg["claude"].get("model", "claude-opus-5-5")
        self.effort = cfg["claude"].get("effort", "high")

    def _create(self, *, effort: str | None = None, output_format: dict | None = None, **kwargs):
        output_config = {"effort": effort or self.effort}
        if output_format:
            output_config["format"] = output_format
        with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=kwargs.pop("max_tokens", 32000),
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config=output_config,
            **kwargs,
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise LLMError(f"Claude rechazó la petición: {response.stop_details}")
        if response.stop_reason == "max_tokens":
            raise LLMError("La respuesta se cortó por max_tokens")
        return response

    @staticmethod
    def _text(response) -> str:
        return "".join(b.text for b in response.content if b.type == "text").strip()

    def json(self, system: str, prompt: str, schema: dict, effort: str | None = None) -> dict:
        """Devuelve un dict que cumple `schema` (structured outputs)."""
        response = self._create(
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format={"type": "json_schema", "schema": schema},
            effort=effort,
        )
        return json.loads(self._text(response))

    def research(self, system: str, prompt: str, max_searches: int = 8) -> str:
        """Investigación con búsqueda web de Anthropic. Devuelve texto con fuentes."""
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
        messages = [{"role": "user", "content": prompt}]
        for _ in range(6):  # gestiona pause_turn en búsquedas largas
            response = self._create(system=system, messages=messages, tools=tools)
            if response.stop_reason != "pause_turn":
                break
            messages = [*messages, {"role": "assistant", "content": response.content}]
        text = self._text(response)
        sources = []
        for block in response.content:
            for cite in getattr(block, "citations", None) or []:
                url = getattr(cite, "url", None)
                if url and url not in sources:
                    sources.append(url)
        if sources:
            text += "\n\nFUENTES:\n" + "\n".join(f"- {u}" for u in sources)
        return text
