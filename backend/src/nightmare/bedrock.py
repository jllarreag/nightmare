"""Thin wrapper over the Bedrock Converse API for Nova 2 Lite with validated JSON output."""

import json
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

ReasoningEffort = Literal["low", "medium"]

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


class ModelOutputError(Exception):
    """The model did not return valid JSON for the expected schema after the retry."""


def extract_text(response: dict[str, Any]) -> str:
    """Join the text blocks of a Converse response, skipping reasoning blocks."""
    content = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(block["text"] for block in content if "text" in block)


def parse_json[T: BaseModel](text: str, schema: type[T]) -> T:
    """Parse model text into the schema, tolerating code fences and surrounding prose."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object found in model output")
    return schema.model_validate(json.loads(cleaned[start : end + 1]))


class NovaClient:
    def __init__(self, client: Any, model_id: str) -> None:
        self._client = client
        self._model_id = model_id

    def converse_json[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_tokens: int = 1500,
        temperature: float = 0.7,
        reasoning: ReasoningEffort | None = None,
    ) -> T:
        """Ask for JSON matching `schema`. Retries once with the validation error as feedback.

        `reasoning` enables Nova 2 extended thinking. "high" is intentionally not allowed:
        it forbids temperature and maxTokens and can produce very long, costly outputs.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": user}]}]
        last_error: Exception | None = None

        for attempt in range(2):
            request: dict[str, Any] = {
                "modelId": self._model_id,
                "system": [{"text": system}],
                "messages": messages,
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
            }
            if reasoning:
                request["additionalModelRequestFields"] = {
                    "reasoningConfig": {"type": "enabled", "maxReasoningEffort": reasoning}
                }

            text = extract_text(self._client.converse(**request))
            try:
                return parse_json(text, schema)
            except (ValueError, ValidationError) as error:
                last_error = error
                # Log the schema and attempt only: model output may echo user text.
                logger.warning(
                    "invalid model output", extra={"schema": schema.__name__, "attempt": attempt}
                )
                messages = messages + [
                    {"role": "assistant", "content": [{"text": text or "{}"}]},
                    {
                        "role": "user",
                        "content": [
                            {
                                "text": "Your previous answer was not valid. Return ONLY one JSON "
                                f"object that fixes this error: {_short(error)}"
                            }
                        ],
                    },
                ]

        raise ModelOutputError(f"invalid output for {schema.__name__}") from last_error


def _short(error: Exception) -> str:
    return str(error).replace("\n", " ")[:500]
