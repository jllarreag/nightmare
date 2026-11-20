"""Tests del backend. Nova, DynamoDB y el guardrail se sustituyen por fakes simples."""

import json

import pytest

from nightmare import ai, db, handler, safety, story
from nightmare.models import ApiError, Category, Session, Step

NIGHTMARE = "Me persigue una sombra por un pasillo oscuro y no puedo correr."


def step_dict(n=1, **extra):
    data = {
        "step": n,
        "title": f"Paso {n}",
        "narration": "Respiras despacio y la niebla se disipa.",
        "technique": ["recreate", "control", "decision", "rewrite", "closing"][n - 1],
        "choices": [{"id": "a", "label": "Abrir"}, {"id": "b", "label": "Respirar"}],
        "image_prompt": "a figure in a foggy corridor" if n in (1, 4) else None,
    }
    if n == 5:
        data.update(choices=[], learning="El miedo se encoge.", coping_tip="Ensaya el final.")
    data.update(extra)
    return data


@pytest.fixture
def fakes(monkeypatch):
    """Sustituye ai.ask, db y safety. `state` permite ajustar el comportamiento en cada test."""
    state = {"category": Category.OK, "safe": True, "sessions": {}, "model_step": step_dict(1)}

    def fake_ask(system, user, parse, **kwargs):
        if parse is story.parse_opening:
            return parse({"summary": "resumen", "step": state["model_step"]})
        return parse(state["model_step"])

    monkeypatch.setattr(ai, "ask", fake_ask)
    monkeypatch.setattr(safety, "classify", lambda text: state["category"])
    monkeypatch.setattr(safety, "output_is_safe", lambda text: state["safe"])
    monkeypatch.setattr(db, "save", lambda s: state["sessions"].__setitem__(s.id, s.to_json()))
    monkeypatch.setattr(
        db,
        "load",
        lambda i: Session.from_json(state["sessions"][i]) if i in state["sessions"] else None,
    )
    monkeypatch.setattr(db, "delete", lambda i: state["sessions"].pop(i, None))
    return state


# --- Step ---------------------------------------------------------------------------------


def test_step_valid_and_public_hides_image_prompt():
    step = Step.from_dict(step_dict(1))
    assert step.public()["has_image"] is True
    assert "image_prompt" not in step.public()


@pytest.mark.parametrize(
    "bad",
    [
        step_dict(1, technique="closing"),  # técnica no corresponde al paso
        step_dict(1, choices=[{"id": "a", "label": "x"}]),  # menos de 2 opciones
        step_dict(1, image_prompt=None),  # el paso 1 necesita imagen
        step_dict(5, choices=[{"id": "a", "label": "x"}, {"id": "b", "label": "y"}]),
        step_dict(1, narration="palabra " * 200),
    ],
)
def test_step_invalid(bad):
    with pytest.raises(ValueError):
        Step.from_dict(bad)


# --- Historia -----------------------------------------------------------------------------


def test_start_validates_input(fakes):
    with pytest.raises(ApiError) as error:
        story.start("corto", "es")
    assert error.value.code == "nightmare_length"
    with pytest.raises(ApiError):
        story.start(NIGHTMARE, "fr")


@pytest.mark.parametrize(
    "category", [Category.RISK, Category.NOT_SERIOUS, Category.FORBIDDEN_CONTENT]
)
def test_start_stops_and_stores_nothing(fakes, category):
    fakes["category"] = category
    result = story.start(NIGHTMARE, "es")
    assert result["status"] == "stopped" and result["category"] == category.value
    assert fakes["sessions"] == {}
    assert (result["resources"] != []) == (category == Category.RISK)


def test_full_story_in_five_steps(fakes):
    result = story.start(NIGHTMARE, "es")
    session_id = result["session_id"]
    for n in range(2, 6):
        fakes["model_step"] = step_dict(n)
        result = story.next_step(session_id, "a")
        assert result["step"]["step"] == n
    assert result["finished"] is True
    with pytest.raises(ApiError) as error:
        story.next_step(session_id, "a")
    assert error.value.status == 409


def test_next_rejects_unknown_session_and_choice(fakes):
    with pytest.raises(ApiError) as error:
        story.next_step("nope", "a")
    assert error.value.status == 404
    session_id = story.start(NIGHTMARE, "es")["session_id"]
    with pytest.raises(ApiError) as error:
        story.next_step(session_id, "zzz")
    assert error.value.code == "choice"


def test_unsafe_output_deletes_the_session(fakes):
    session_id = story.start(NIGHTMARE, "es")["session_id"]
    fakes.update(safe=False, model_step=step_dict(2))
    assert story.next_step(session_id, "a")["status"] == "stopped"
    assert fakes["sessions"] == {}


# --- Handler HTTP -------------------------------------------------------------------------


def call(route, body, path=None):
    event = {"routeKey": route, "body": json.dumps(body), "pathParameters": path}
    response = handler.handler(event, None)
    return response["statusCode"], json.loads(response["body"])


def test_handler_routes_and_errors(fakes):
    status, body = call("POST /sessions", {"nightmare": NIGHTMARE, "language": "es"})
    assert status == 200 and body["status"] == "ok"
    fakes["model_step"] = step_dict(2)
    status, _ = call(
        "POST /sessions/{session_id}/steps", {"choice_id": "a"}, {"session_id": body["session_id"]}
    )
    assert status == 200
    assert call("POST /sessions", {"language": "xx"}) == (400, {"error": "language"})
    assert call("GET /otra", {}) == (404, {"error": "not_found"})
    bad = handler.handler({"routeKey": "POST /sessions", "body": "no json"}, None)
    assert bad["statusCode"] == 400


def test_handler_hides_unexpected_errors(monkeypatch):
    def boom(*args):
        raise RuntimeError("texto secreto del usuario")

    monkeypatch.setattr(story, "start", boom)
    status, body = call("POST /sessions", {})
    assert (status, body) == (500, {"error": "internal"})
