"""Moderación: Bedrock Guardrail + clasificador de Nova. Nunca se registra texto del usuario."""

import json
import os

from nightmare import ai, prompts
from nightmare.models import Category

GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "DRAFT")
SELF_HARM_TOPIC = "SelfHarm"  # nombre del topic en infra/stacks/guardrail.py


def guardrail(text: str, source: str) -> str:
    """Pasa el texto por el guardrail. Devuelve "ok", "blocked" o "risk" (autolesión)."""
    if not GUARDRAIL_ID:
        return "ok"
    response = ai.client.apply_guardrail(
        guardrailIdentifier=GUARDRAIL_ID,
        guardrailVersion=GUARDRAIL_VERSION,
        source=source,  # "INPUT" o "OUTPUT"
        content=[{"text": {"text": text}}],
    )
    if response.get("action") != "GUARDRAIL_INTERVENED":
        return "ok"
    if SELF_HARM_TOPIC in json.dumps(response.get("assessments", [])):
        return "risk"
    return "blocked"


def classify(text: str) -> Category:
    """Clasifica la pesadilla del usuario. Solo `ok` permite continuar. `risk` siempre gana."""
    blocked = guardrail(text, "INPUT")
    if blocked == "risk":
        return Category.RISK
    category = ai.ask(
        prompts.CLASSIFIER_SYSTEM,
        prompts.classifier_user(text),
        parse=lambda data: Category(data["category"]),
        temperature=0.0,
        max_tokens=200,
    )
    if category == Category.RISK:
        return category
    return Category.FORBIDDEN_CONTENT if blocked == "blocked" else category


def output_is_safe(text: str) -> bool:
    return guardrail(text, "OUTPUT") == "ok"
