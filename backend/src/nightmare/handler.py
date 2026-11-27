"""Lambda única de la API. Enruta por `routeKey` y traduce errores a respuestas HTTP.

    POST /sessions                      {"nightmare": str, "language": "es" | "en"}
    POST /sessions/{session_id}/steps   {"choice_id": str}
    GET /sessions/{session_id}/images   estado de las imagenes (pending | ready | failed)
    POST /sessions/{session_id}/publish {"consent": true}
    GET /gallery?language=&limit=&cursor=
    DELETE /gallery/{story_id}          header x-delete-token

No se registran cuerpos ni mensajes de excepción: pueden contener texto del usuario.
"""

import base64
import json
import logging

from botocore.exceptions import ClientError

from nightmare import gallery, images, story
from nightmare.models import ApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

THROTTLING = {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}


def respond(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def read_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw)
    except ValueError:
        raise ApiError(400, "body") from None
    if not isinstance(body, dict):
        raise ApiError(400, "body")
    return body


def parse_limit(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ApiError(400, "limit") from None


def handler(event, context):
    try:
        body = read_body(event)
        route = event.get("routeKey")
        if route == "POST /sessions":
            result = story.start(body.get("nightmare"), body.get("language"))
        elif route == "POST /sessions/{session_id}/steps":
            session_id = (event.get("pathParameters") or {}).get("session_id")
            result = story.next_step(session_id, body.get("choice_id"))
        elif route == "GET /sessions/{session_id}/images":
            session_id = (event.get("pathParameters") or {}).get("session_id")
            result = images.status(session_id)
        elif route == "POST /sessions/{session_id}/publish":
            session_id = (event.get("pathParameters") or {}).get("session_id")
            result = gallery.publish(session_id, body.get("consent"))
        elif route == "GET /gallery":
            query = event.get("queryStringParameters") or {}
            result = gallery.list_stories(
                query.get("language"), parse_limit(query.get("limit")), query.get("cursor")
            )
        elif route == "DELETE /gallery/{story_id}":
            story_id = (event.get("pathParameters") or {}).get("story_id")
            result = gallery.delete(story_id, (event.get("headers") or {}).get("x-delete-token"))
        else:
            raise ApiError(404, "not_found")
        return respond(200, result)
    except ApiError as error:
        return respond(error.status, {"error": error.code})
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        # El mensaje de AWS no lleva texto del usuario y explica bloqueos de cuenta o de cuota.
        message = error.response.get("Error", {}).get("Message", "")
        logger.warning("aws error: %s | %s", code, message)
        return (
            respond(429, {"error": "busy"})
            if code in THROTTLING
            else respond(503, {"error": "unavailable"})
        )
    except Exception as error:  # noqa: BLE001 - último recurso, sin filtrar detalles
        logger.error("unhandled error: %s", type(error).__name__)
        return respond(500, {"error": "internal"})
