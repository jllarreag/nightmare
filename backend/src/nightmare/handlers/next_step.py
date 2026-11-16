"""POST /sessions/{session_id}/steps  {"choice_id": str}"""

import re
from typing import Any

from nightmare import wiring
from nightmare.api import Event, Response, handle, json_response, parse_body
from nightmare.story import InvalidRequest, SessionNotFound

_SESSION_ID = re.compile(r"^[0-9a-f]{32}$")


@handle
def handler(event: Event, context: Any) -> Response:
    session_id = (event.get("pathParameters") or {}).get("session_id", "")
    if not _SESSION_ID.match(session_id):
        raise SessionNotFound(session_id)

    choice_id = parse_body(event).get("choice_id")
    if not isinstance(choice_id, str) or not choice_id:
        raise InvalidRequest("choice")

    return json_response(200, wiring.story_service().next(session_id, choice_id))
