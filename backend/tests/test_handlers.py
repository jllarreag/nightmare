import base64
import json

import pytest
from botocore.exceptions import ClientError

from nightmare import wiring
from nightmare.bedrock import ModelOutputError
from nightmare.handlers import next_step, start_session
from nightmare.store import ConcurrentUpdate
from nightmare.story import InvalidRequest, SessionFinished, SessionNotFound

SESSION_ID = "c" * 32


class FakeService:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def start(self, nightmare, language):
        self.calls.append(("start", nightmare, language))
        if self.error:
            raise self.error
        return {"status": "ok", "session_id": SESSION_ID}

    def next(self, session_id, choice_id):
        self.calls.append(("next", session_id, choice_id))
        if self.error:
            raise self.error
        return {"status": "ok", "session_id": session_id}


@pytest.fixture
def fake(monkeypatch):
    def install(error=None):
        svc = FakeService(error)
        monkeypatch.setattr(wiring, "story_service", lambda: svc)
        return svc

    return install


def call_start(body, *, encoded=False):
    raw = json.dumps(body) if not isinstance(body, str) else body
    if encoded:
        raw = base64.b64encode(raw.encode()).decode()
    response = start_session.handler({"body": raw, "isBase64Encoded": encoded}, None)
    return response["statusCode"], json.loads(response["body"])


def call_next(session_id, body):
    event = {"pathParameters": {"session_id": session_id}, "body": json.dumps(body)}
    response = next_step.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def test_start_ok_and_base64_bodies(fake):
    svc = fake()

    assert call_start({"nightmare": "sueño", "language": "es"}) == (
        200,
        {"status": "ok", "session_id": SESSION_ID},
    )
    assert call_start({"nightmare": "dream", "language": "en"}, encoded=True)[0] == 200
    assert svc.calls[0] == ("start", "sueño", "es")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ("not json", "body"),
        ("[1, 2]", "body"),
        ({"nightmare": "x", "language": "fr"}, "language"),
        ({"language": "es"}, "nightmare"),
        ({"nightmare": 42, "language": "es"}, "nightmare"),
    ],
)
def test_start_validation_errors(fake, body, code):
    svc = fake()

    assert call_start(body) == (400, {"error": code})
    assert svc.calls == []


def test_next_ok(fake):
    svc = fake()

    assert call_next(SESSION_ID, {"choice_id": "a"})[0] == 200
    assert svc.calls == [("next", SESSION_ID, "a")]


@pytest.mark.parametrize(
    ("session_id", "body", "status"),
    [
        ("../etc/passwd", {"choice_id": "a"}, 404),
        (SESSION_ID, {}, 400),
        (SESSION_ID, {"choice_id": ""}, 400),
    ],
)
def test_next_validation(fake, session_id, body, status):
    svc = fake()

    assert call_next(session_id, body)[0] == status
    assert svc.calls == []


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "m"}}, "Converse")


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (InvalidRequest("choice"), 400, "choice"),
        (SessionNotFound("x"), 404, "session_not_found"),
        (SessionFinished("x"), 409, "session_conflict"),
        (ConcurrentUpdate("x"), 409, "session_conflict"),
        (ModelOutputError("bad"), 502, "generation_failed"),
        (client_error("ThrottlingException"), 429, "busy"),
        (client_error("AccessDeniedException"), 503, "unavailable"),
        (RuntimeError("secret user text"), 500, "internal"),
    ],
)
def test_errors_map_to_http_without_leaking_details(fake, error, status, code):
    fake(error)

    response_status, body = call_next(SESSION_ID, {"choice_id": "a"})

    assert (response_status, body) == (status, {"error": code})
