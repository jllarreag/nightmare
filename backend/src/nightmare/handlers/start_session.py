"""POST /sessions  {"nightmare": str, "language": "es" | "en"}"""

from typing import Any

from nightmare import wiring
from nightmare.api import Event, Response, handle, json_response, parse_body
from nightmare.story import InvalidRequest


@handle
def handler(event: Event, context: Any) -> Response:
    body = parse_body(event)

    language = body.get("language")
    if language not in ("es", "en"):
        raise InvalidRequest("language")
    nightmare = body.get("nightmare")
    if not isinstance(nightmare, str):
        raise InvalidRequest("nightmare")

    return json_response(200, wiring.story_service().start(nightmare, language))
