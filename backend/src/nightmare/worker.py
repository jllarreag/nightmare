"""Lambda ImageWorker: genera la imagen de un paso. La invoca la API en segundo plano.

Evento: {"session_id": str, "step": int}. Nunca lanza (el reintento asincrono esta desactivado
y duplicaria llamadas de pago); el resultado queda en DynamoDB como ready o failed.
"""

import logging

from nightmare import images
from nightmare.models import IMAGE_STEPS

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    session_id = event.get("session_id") if isinstance(event, dict) else None
    step = event.get("step") if isinstance(event, dict) else None
    if not isinstance(session_id, str) or isinstance(step, bool) or step not in IMAGE_STEPS:
        logger.warning("invalid image event")
        return {"status": "ignored"}
    return {"status": images.generate(session_id, step)}
