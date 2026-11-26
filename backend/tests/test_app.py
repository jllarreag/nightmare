"""Tests del backend. Nova, DynamoDB y el guardrail se sustituyen por fakes simples."""

import json
from types import SimpleNamespace

import pytest

from nightmare import ai, db, gallery, handler, prompts, safety, story
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
    state = {
        "category": Category.OK,
        "safe": True,
        "sessions": {},
        "stories": {},
        "model_step": step_dict(1),
    }

    def fake_ask(system, user, parse, **kwargs):
        if system == prompts.ANONYMIZER_SYSTEM:
            steps = [{**step_dict(n), "narration": "Texto anonimo."} for n in range(1, 6)]
            return parse({"steps": steps})
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
    monkeypatch.setattr(
        db, "put_story", lambda item: state["stories"].__setitem__(item["id"], item)
    )
    monkeypatch.setattr(db, "get_story", lambda i: state["stories"].get(i))
    monkeypatch.setattr(db, "delete_story", lambda i: state["stories"].pop(i, None))

    def fake_query(language, limit, start_key, now):
        items = [
            i
            for i in sorted(state["stories"].values(), key=lambda i: i["gsk"], reverse=True)
            if i["language"] == language and i.get("ttl", now + 1) > now
        ]
        if start_key:
            items = [i for i in items if i["gsk"] < start_key["gsk"]]
        page, rest = items[:limit], items[limit:]
        if not page:
            return [], None
        pk = "STORY#" + page[-1]["id"]
        last = {"pk": pk, "gpk": page[-1]["gpk"], "gsk": page[-1]["gsk"]}
        return page, (last if rest else None)

    monkeypatch.setattr(db, "query_stories", fake_query)
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


def call(route, body, path=None, query=None, headers=None):
    event = {
        "routeKey": route,
        "body": json.dumps(body),
        "pathParameters": path,
        "queryStringParameters": query,
        "headers": headers or {},
    }
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


# --- Galería ------------------------------------------------------------------------------
def finished_session(fakes):
    fakes["model_step"] = step_dict(1)
    session_id = story.start(NIGHTMARE, "es")["session_id"]
    for n in range(2, 6):
        fakes["model_step"] = step_dict(n)
        story.next_step(session_id, "a")
    return session_id


def test_publish_requires_consent_and_a_finished_story(fakes):
    session_id = story.start(NIGHTMARE, "es")["session_id"]
    with pytest.raises(ApiError) as error:
        gallery.publish(session_id, True)
    assert (error.value.status, error.value.code) == (409, "session_not_finished")
    with pytest.raises(ApiError) as error:
        gallery.publish(session_id, None)
    assert (error.value.status, error.value.code) == (400, "consent")
    with pytest.raises(ApiError) as error:
        gallery.publish("nope", True)
    assert error.value.status == 404
    assert fakes["stories"] == {}


def test_publish_stores_only_the_allowed_fields_and_a_token_hash(fakes):
    session_id = finished_session(fakes)
    result = gallery.publish(session_id, True)
    item = fakes["stories"][result["story_id"]]
    assert item["token_hash"] == gallery.hash_token(result["delete_token"])
    assert item["token_hash"] != result["delete_token"]
    assert result["delete_token"] not in json.dumps(item)
    stored = json.loads(item["story"])
    assert [s["step"] for s in stored] == [1, 2, 3, 4, 5]
    allowed = {"step", "title", "narration", "learning", "coping_tip", "has_image", "image"}
    assert set(stored[0]) == allowed
    assert stored[0]["has_image"] is True and stored[0]["image"] is None
    assert not {"summary", "choices", "image_prompt", "session_id"} & set(item)
    assert item["ttl"] == result["expires_at"]


def test_unsafe_anonymized_text_is_not_published(fakes):
    session_id = finished_session(fakes)
    fakes["safe"] = False
    with pytest.raises(ApiError) as error:
        gallery.publish(session_id, True)
    assert (error.value.status, error.value.code) == (422, "not_publishable")
    assert fakes["stories"] == {}
    assert Session.from_json(fakes["sessions"][session_id]).published is False


def test_a_session_is_published_only_once(fakes):
    session_id = finished_session(fakes)
    gallery.publish(session_id, True)
    with pytest.raises(ApiError) as error:
        gallery.publish(session_id, True)
    assert (error.value.status, error.value.code) == (409, "already_published")
    assert len(fakes["stories"]) == 1


def test_delete_needs_the_right_token(fakes):
    result = gallery.publish(finished_session(fakes), True)
    attempts = [
        (result["story_id"], "wrong"),
        ("unknown", result["delete_token"]),
        (result["story_id"], None),
    ]
    for story_id, token in attempts:
        with pytest.raises(ApiError) as error:
            gallery.delete(story_id, token)
        assert (error.value.status, error.value.code) == (404, "not_found")
    assert result["story_id"] in fakes["stories"]
    assert gallery.delete(result["story_id"], result["delete_token"]) == {"status": "deleted"}
    assert fakes["stories"] == {}


def test_list_validates_params(fakes):
    for args in (("fr", None, None), ("es", 21, None), ("es", 0, None), ("es", None, "garbage")):
        with pytest.raises(ApiError) as error:
            gallery.list_stories(*args)
        assert error.value.status == 400


def test_list_is_newest_first_hides_secrets_and_paginates(fakes, monkeypatch):
    clock = iter([1000, 2000, 3000])
    monkeypatch.setattr(gallery, "time", SimpleNamespace(time=lambda: next(clock)))
    ids = [gallery.publish(finished_session(fakes), True)["story_id"] for _ in range(3)]
    monkeypatch.setattr(gallery, "time", SimpleNamespace(time=lambda: 5))
    first = gallery.list_stories("es", 2, None)
    assert [s["id"] for s in first["stories"]] == [ids[2], ids[1]]
    assert first["next_cursor"]
    assert "token_hash" not in json.dumps(first)
    second = gallery.list_stories("es", 2, first["next_cursor"])
    assert [s["id"] for s in second["stories"]] == [ids[0]] and second["next_cursor"] is None
    assert gallery.list_stories("en", None, None) == {"stories": [], "next_cursor": None}
    with pytest.raises(ApiError):
        gallery.list_stories("en", 2, first["next_cursor"])  # cursor de otro idioma


def test_list_skips_expired_stories(fakes):
    result = gallery.publish(finished_session(fakes), True)
    fakes["stories"][result["story_id"]]["ttl"] = 1
    assert gallery.list_stories("es", None, None)["stories"] == []


def test_handler_publish_list_delete_flow(fakes):
    started = call("POST /sessions", {"nightmare": NIGHTMARE, "language": "es"})[1]
    session = {"session_id": started["session_id"]}
    for n in range(2, 6):
        fakes["model_step"] = step_dict(n)
        call("POST /sessions/{session_id}/steps", {"choice_id": "a"}, session)
    status, body = call("POST /sessions/{session_id}/publish", {"consent": True}, session)
    assert status == 200
    status, listed = call("GET /gallery", {}, query={"language": "es", "limit": "6"})
    assert status == 200 and [s["id"] for s in listed["stories"]] == [body["story_id"]]
    story_path = {"story_id": body["story_id"]}
    assert call("DELETE /gallery/{story_id}", {}, story_path)[0] == 404
    headers = {"x-delete-token": body["delete_token"]}
    assert call("DELETE /gallery/{story_id}", {}, story_path, headers=headers)[0] == 200
    assert call("GET /gallery", {}, query={"language": "es"})[1]["stories"] == []
    bad_limit = call("GET /gallery", {}, query={"language": "es", "limit": "x"})
    assert bad_limit == (400, {"error": "limit"})


def test_handler_hides_unexpected_publish_errors(monkeypatch):
    def boom(*args):
        raise RuntimeError("texto secreto del usuario")

    monkeypatch.setattr(gallery, "publish", boom)
    path = {"session_id": "s"}
    status, body = call("POST /sessions/{session_id}/publish", {"consent": True}, path)
    assert (status, body) == (500, {"error": "internal"})


# --- DynamoDB (tabla falsa) ---------------------------------------------------------------
class FakeTable:
    def __init__(self):
        self.puts, self.queries = [], []

    def put_item(self, **kwargs):
        self.puts.append(kwargs)

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"Items": [{"id": "x"}], "LastEvaluatedKey": {"pk": "k"}}


def test_put_story_writes_the_story_key(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(db, "table", table)
    db.put_story({"id": "abc", "gpk": "GALLERY#es"})
    assert table.puts == [{"Item": {"pk": "STORY#abc", "id": "abc", "gpk": "GALLERY#es"}}]


def test_query_stories_uses_the_gallery_index_newest_first(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(db, "table", table)
    items, last = db.query_stories("es", 6, None, 100)
    assert items == [{"id": "x"}] and last == {"pk": "k"}
    args = table.queries[0]
    assert args["IndexName"] == "gallery" and args["ScanIndexForward"] is False
    assert args["Limit"] == 6 and "ExclusiveStartKey" not in args and "FilterExpression" in args
    db.query_stories("es", 6, {"pk": "k"}, 100)
    assert table.queries[1]["ExclusiveStartKey"] == {"pk": "k"}
