"""Translation between API Gateway HTTP API events (payload v2) and the story engine.

Errors are returned as stable codes; the frontend shows the localized message.
Nothing here logs request bodies or exception messages, which may contain user text.
"""

import base64
import functools
import json
import logging
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from nightmare.bedrock import ModelOutputError
from nightmare.store import ConcurrentUpdate
from nightmare.story import InvalidRequest, SessionFinished, SessionNotFound

logger = logging.getLogger(__name__)

Event = dict[str, Any]
Response = dict[str, Any]

_THROTTLING = {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}


def json_response(status: int, body: dict[str, Any]) -> Response:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(body, ensure_ascii=False),
    }


def parse_body(event: Event) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        body = json.loads(raw)
    except ValueError as error:
        raise InvalidRequest("body") from error
    if not isinstance(body, dict):
        raise InvalidRequest("body")
    return body


def handle(function: Callable[[Event, Any], Response]) -> Callable[[Event, Any], Response]:
    """Map domain and AWS errors to HTTP responses."""

    @functools.wraps(function)
    def wrapper(event: Event, context: Any) -> Response:
        try:
            return function(event, context)
        except InvalidRequest as error:
            return json_response(400, {"error": error.code})
        except SessionNotFound:
            return json_response(404, {"error": "session_not_found"})
        except (SessionFinished, ConcurrentUpdate):
            return json_response(409, {"error": "session_conflict"})
        except ModelOutputError:
            logger.warning("model output invalid after retry")
            return json_response(502, {"error": "generation_failed"})
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            logger.warning("aws error", extra={"code": code})
            if code in _THROTTLING:
                return json_response(429, {"error": "busy"})
            return json_response(503, {"error": "unavailable"})
        except Exception as error:  # noqa: BLE001 - last resort, never leak details
            logger.error("unhandled error", extra={"type": type(error).__name__})
            return json_response(500, {"error": "internal"})

    return wrapper
