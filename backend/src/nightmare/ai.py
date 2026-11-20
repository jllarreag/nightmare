"""Llamada a Nova 2 Lite que devuelve JSON ya validado."""

import json
import os
import re

import boto3
from botocore.config import Config

from nightmare.models import ApiError

# Clientes a nivel de módulo: Lambda los reutiliza entre invocaciones.
REGION = os.environ.get("BASE_REGION", "eu-south-2")
MODEL_ID = os.environ.get("TEXT_MODEL_ID", "eu.amazon.nova-2-lite-v1:0")
# API Gateway corta a los 30 s: Bedrock debe responder antes.
client = boto3.client(
    "bedrock-runtime",
    region_name=REGION,
    config=Config(read_timeout=20, connect_timeout=5, retries={"max_attempts": 2}),
)


def ask(system, user, parse, max_tokens=1500, temperature=0.7, reasoning=None):
    """Pide JSON al modelo y lo convierte con `parse(dict)`. Reintenta una vez si falla.

    `parse` debe lanzar ValueError/KeyError/TypeError si el JSON no es válido.
    `reasoning` ("low" o "medium") activa el razonamiento extendido de Nova.
    """
    request = {
        "modelId": MODEL_ID,
        "system": [{"text": system}],
        "messages": [{"role": "user", "content": [{"text": user}]}],
        "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
    }
    if reasoning:
        request["additionalModelRequestFields"] = {
            "reasoningConfig": {"type": "enabled", "maxReasoningEffort": reasoning}
        }
    for _ in range(2):
        response = client.converse(**request)
        blocks = response["output"]["message"]["content"]
        text = "".join(b["text"] for b in blocks if "text" in b)
        try:
            return parse(extract_json(text))
        except (ValueError, KeyError, TypeError):
            pass  # no registramos el texto: puede contener datos del usuario
    raise ApiError(502, "generation_failed")


def extract_json(text: str) -> dict:
    """Devuelve el primer objeto JSON del texto (tolera ```json ...``` y texto alrededor)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("no JSON in model output")
    return json.loads(match.group(0))
