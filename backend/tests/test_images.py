"""Tests de imagenes. Nova, guardrail, Stability, S3, Lambda y DynamoDB son fakes."""

import base64
import json

import pytest
from botocore.exceptions import ClientError
from hypothesis import given
from hypothesis import strategies as st

from nightmare import ai, db, gallery, images, prompts, safety, story, worker
from nightmare.models import ApiError, Session, Step
from test_app import NIGHTMARE, call, finished_session, step_dict
from test_app import fakes as base_fakes  # noqa: F401 - fixture reutilizada

NARRATION = "Maria camina por la calle Mayor de Sevilla con su hermano Pedro."
JPEG = b"\xff\xd8fake-jpeg"
SCENE = "A small figure walks along a quiet foggy street"


class FakeBody:
    def __init__(self, data):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode()


class FakeImageClient:
    def __init__(self, fail_models=(), finish=None):
        self.calls, self.fail_models, self.finish = [], fail_models, finish

    def invoke_model(self, modelId, body, **kwargs):
        self.calls.append((modelId, json.loads(body)))
        if modelId in self.fail_models:
            raise ClientError({"Error": {"Code": "ThrottlingException"}}, "InvokeModel")
        data = {"finish_reasons": [self.finish], "images": [base64.b64encode(JPEG).decode()]}
        return {"body": FakeBody(data)}


class FakeS3:
    def __init__(self):
        self.objects, self.deleted, self.copies = {}, [], []

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.objects[Key] = (Body, kwargs)

    def copy_object(self, Bucket, Key, CopySource):
        self.copies.append((CopySource["Key"], Key))
        self.objects[Key] = self.objects[CopySource["Key"]]

    def delete_objects(self, Bucket, Delete):
        self.deleted += [o["Key"] for o in Delete["Objects"]]

    def generate_presigned_url(self, op, Params, ExpiresIn):
        return f"https://signed/{Params['Key']}?exp={ExpiresIn}"


class FakeLambda:
    def __init__(self, fail=False):
        self.invocations, self.fail = [], fail

    def invoke(self, **kwargs):
        if self.fail:
            raise ClientError({"Error": {"Code": "AccessDenied"}}, "Invoke")
        self.invocations.append(kwargs)


@pytest.fixture
def env(base_fakes, monkeypatch):  # noqa: F811
    """Imagenes activadas: fakes de Stability, S3, Lambda, DynamoDB y Nova (escena/veredicto)."""
    state = base_fakes  # mismo dict: test_app.fake_ask lee de el `model_step`
    state.update(
        images={},
        scene=SCENE,
        verdict="ok",
        guardrail="ok",
        client=FakeImageClient(),
        s3=FakeS3(),
        **{"lambda": FakeLambda()},
    )
    base_ask = ai.ask

    def fake_ask(system, user, parse, **kwargs):
        if system == prompts.IMAGE_SCENE_SYSTEM:
            return parse({"scene": state["scene"]})
        if system == prompts.IMAGE_MODERATION_SYSTEM:
            return parse({"verdict": state["verdict"]})
        return base_ask(system, user, parse, **kwargs)

    monkeypatch.setattr(ai, "ask", fake_ask)
    monkeypatch.setattr(safety, "guardrail", lambda text, source: state["guardrail"])
    monkeypatch.setattr(images, "image_client", state["client"])
    monkeypatch.setattr(images, "s3", state["s3"])
    monkeypatch.setattr(images, "lambda_client", state["lambda"])
    monkeypatch.setattr(images, "IMAGE_BUCKET", "bucket")
    monkeypatch.setattr(images, "IMAGE_WORKER_FUNCTION", "worker")

    def put_image(session_id, step, status, key=None):
        state["images"][(session_id, step)] = {"status": status, "key": key}

    monkeypatch.setattr(db, "put_image", put_image)
    monkeypatch.setattr(db, "get_image", lambda sid, step: state["images"].get((sid, step)))
    return state


def stored_session(env, character="a small figure in a grey coat"):
    session = Session(
        id="s1",
        language="es",
        summary="resumen",
        history=[Step.from_dict(step_dict(1, narration=NARRATION))],
        character=character,
    )
    env["sessions"]["s1"] = session.to_json()
    return session


# --- Prompt y semilla ---------------------------------------------------------------------


@given(st.text(max_size=40), st.text(max_size=40), st.text(min_size=1, max_size=40))
def test_prompt_ends_with_the_style_suffix_and_seed_is_stable(character, scene, session_id):
    assert images.build_prompt(character, scene).endswith(prompts.IMAGE_STYLE_SUFFIX)
    value = images.seed(session_id)
    assert 0 <= value <= 4294967294 and value == images.seed(session_id)


def test_prompt_is_character_scene_and_suffix():
    prompt = images.build_prompt("A small figure.", "Walks in the fog")
    assert prompt == f"A small figure. Walks in the fog. {prompts.IMAGE_STYLE_SUFFIX}"
    assert images.build_prompt("", "Walks") == f"Walks. {prompts.IMAGE_STYLE_SUFFIX}"


def test_parsers_reject_invalid_output():
    for bad in ({"scene": ""}, {"scene": "word " * 61}, {}):
        with pytest.raises((ValueError, KeyError)):
            images.parse_scene(bad)
    with pytest.raises(ValueError):
        images.parse_verdict({"verdict": "maybe"})


# --- generate -----------------------------------------------------------------------------


def test_generate_stores_the_image_and_marks_it_ready(env):
    stored_session(env)
    assert images.generate("s1", 1) == "ready"
    body, extra = env["s3"].objects["sessions/s1/1.jpg"]
    assert body == JPEG and extra["ContentType"] == "image/jpeg"
    assert env["images"][("s1", 1)] == {"status": "ready", "key": "sessions/s1/1.jpg"}
    model, request = env["client"].calls[0]
    assert model == images.IMAGE_MODEL_ID and "mode" not in request
    assert request["prompt"].endswith(prompts.IMAGE_STYLE_SUFFIX)
    assert request["seed"] == images.seed("s1")


def test_stability_never_receives_the_narration(env):
    stored_session(env)
    images.generate("s1", 1)
    sent = json.dumps(env["client"].calls)
    for word in ("Maria", "Pedro", "Sevilla", "calle Mayor", NARRATION):
        assert word not in sent


@pytest.mark.parametrize(
    "change",
    [
        {"scene": "A pool of blood on the floor"},
        {"scene": "A naked figure"},
        {"guardrail": "blocked"},
        {"verdict": "unsafe"},
    ],
)
def test_unsafe_prompts_fail_closed_without_calling_stability(env, change):
    stored_session(env)
    env.update(change)
    assert images.generate("s1", 1) == "failed"
    assert env["client"].calls == [] and env["s3"].objects == {}
    assert env["images"][("s1", 1)] == {"status": "failed", "key": None}


def test_the_style_suffix_does_not_trip_the_deny_list(env):
    stored_session(env)
    assert images.generate("s1", 1) == "ready"  # el sufijo dice "no gore, no nudity"


def test_fallback_model_is_used_on_client_error(env):
    stored_session(env)
    env["client"].fail_models = (images.IMAGE_MODEL_ID,)
    assert images.generate("s1", 1) == "ready"
    models = [m for m, _ in env["client"].calls]
    assert models == [images.IMAGE_MODEL_ID, images.IMAGE_FALLBACK_MODEL_ID]
    assert env["client"].calls[1][1]["mode"] == "text-to-image"


def test_both_models_failing_marks_failed(env):
    stored_session(env)
    env["client"].fail_models = (images.IMAGE_MODEL_ID, images.IMAGE_FALLBACK_MODEL_ID)
    assert images.generate("s1", 1) == "failed"


def test_filtered_image_is_a_failure_without_fallback(env):
    stored_session(env)
    env["client"].finish = "CONTENT_FILTERED"
    assert images.generate("s1", 1) == "failed"
    assert len(env["client"].calls) == 1


def test_generate_swallows_every_exception(env, monkeypatch):
    stored_session(env)

    def boom(*args, **kwargs):
        raise RuntimeError("texto secreto")

    monkeypatch.setattr(images, "render", boom)
    assert images.generate("s1", 1) == "failed"
    assert env["images"][("s1", 1)]["status"] == "failed"
    assert images.generate("unknown", 1) == "failed"
    assert images.generate("s1", 2) == "failed"  # el paso 2 no tiene imagen


def test_generate_survives_a_failing_state_write(env, monkeypatch):
    stored_session(env)

    def boom(*args, **kwargs):
        raise RuntimeError("dynamodb")

    monkeypatch.setattr(db, "put_image", boom)
    assert images.generate("s1", 1) == "failed"


def test_worker_validates_the_event(env):
    stored_session(env)
    assert worker.handler({"session_id": "s1", "step": 1}, None) == {"status": "ready"}
    for bad in ({}, {"session_id": 3, "step": 1}, {"session_id": "s1", "step": 2}, None):
        assert worker.handler(bad, None) == {"status": "ignored"}
    assert worker.handler({"session_id": "s1", "step": True}, None) == {"status": "ignored"}


# --- request ------------------------------------------------------------------------------


def test_request_is_a_noop_without_env(env, monkeypatch):
    session = stored_session(env)
    monkeypatch.setattr(images, "IMAGE_WORKER_FUNCTION", "")
    images.request(session, 1)
    monkeypatch.setattr(images, "IMAGE_WORKER_FUNCTION", "worker")
    monkeypatch.setattr(images, "IMAGE_BUCKET", "")
    images.request(session, 1)
    assert env["images"] == {} and env["lambda"].invocations == []


def test_request_writes_pending_and_sends_only_ids(env):
    session = stored_session(env)
    images.request(session, 1)
    assert env["images"][("s1", 1)]["status"] == "pending"
    call_args = env["lambda"].invocations[0]
    assert call_args["InvocationType"] == "Event" and call_args["FunctionName"] == "worker"
    assert json.loads(call_args["Payload"]) == {"session_id": "s1", "step": 1}


def test_request_records_failed_when_the_invoke_fails(env):
    session = stored_session(env)
    env["lambda"].fail = True
    images.request(session, 1)
    assert env["images"][("s1", 1)]["status"] == "failed"


def test_story_start_is_ok_even_if_the_image_request_raises(env, monkeypatch):
    def boom(*args):
        raise RuntimeError("boom")

    monkeypatch.setattr(images, "request", boom)
    assert story.start(NIGHTMARE, "es")["status"] == "ok"


def test_story_requests_images_for_steps_1_and_4_only(env):
    session_id = finished_session(env)
    sent = [json.loads(i["Payload"])["step"] for i in env["lambda"].invocations]
    assert sent == [1, 4]
    assert all(
        json.loads(i["Payload"])["session_id"] == session_id for i in env["lambda"].invocations
    )


def test_character_is_stored_in_the_session(env, monkeypatch):
    opening = ("resumen", Step.from_dict(step_dict(1)), "a small figure")
    monkeypatch.setattr(ai, "ask", lambda system, user, parse, **kwargs: opening)
    session_id = story.start(NIGHTMARE, "es")["session_id"]
    assert Session.from_json(env["sessions"][session_id]).character == "a small figure"


def test_parse_opening_reads_the_optional_character():
    data = {"summary": "r", "step": step_dict(1)}
    assert story.parse_opening(data)[2] == ""
    assert story.parse_opening({**data, "character": "  a figure  "})[2] == "a figure"
    assert story.parse_opening({**data, "character": 5})[2] == ""
    assert len(story.parse_opening({**data, "character": "x" * 500})[2]) == 200


# --- Ruta GET /sessions/{id}/images -------------------------------------------------------


def test_images_route_reports_unknown_pending_ready_and_missing(env):
    path = {"session_id": "s1"}
    assert call("GET /sessions/{session_id}/images", {}, path) == (
        404,
        {"error": "session_not_found"},
    )
    session = stored_session(env)
    session.history.append(Step.from_dict(step_dict(2)))
    session.history.append(Step.from_dict(step_dict(3)))
    session.history.append(Step.from_dict(step_dict(4)))
    env["sessions"]["s1"] = session.to_json()
    route = "GET /sessions/{session_id}/images"

    status, body = call(route, {}, path)  # sin items: fallo
    assert status == 200 and body == {
        "images": {"1": {"status": "failed", "url": None}, "4": {"status": "failed", "url": None}}
    }
    env["images"][("s1", 1)] = {"status": "pending", "key": None}
    env["images"][("s1", 4)] = {"status": "ready", "key": "sessions/s1/4.jpg"}
    body = call(route, {}, path)[1]["images"]
    assert body["1"] == {"status": "pending", "url": None}
    assert body["4"] == {"status": "ready", "url": "https://signed/sessions/s1/4.jpg?exp=3600"}
    env["images"][("s1", 1)] = {"status": "failed", "key": None}
    assert call(route, {}, path)[1]["images"]["1"] == {"status": "failed", "url": None}


def test_url_is_none_without_key_or_bucket(env, monkeypatch):
    assert images.url(None) is None
    monkeypatch.setattr(images, "IMAGE_BUCKET", "")
    assert images.url("sessions/s1/1.jpg") is None


# --- Galeria ------------------------------------------------------------------------------


def test_publish_copies_only_ready_images_and_list_returns_urls(env):
    session_id = finished_session(env)
    env["images"][(session_id, 1)] = {"status": "ready", "key": f"sessions/{session_id}/1.jpg"}
    env["s3"].objects[f"sessions/{session_id}/1.jpg"] = (JPEG, {})
    env["images"][(session_id, 4)] = {"status": "pending", "key": None}
    result = gallery.publish(session_id, True)
    story_id = result["story_id"]
    stored = json.loads(env["stories"][story_id]["story"])
    assert stored[0]["image"] == f"gallery/{story_id}/1.jpg"  # clave, no URL
    assert [s["image"] for s in stored[1:]] == [None, None, None, None]
    assert env["s3"].copies == [(f"sessions/{session_id}/1.jpg", f"gallery/{story_id}/1.jpg")]
    listed = gallery.list_stories("es", None, None)["stories"][0]["steps"]
    assert listed[0]["image"] == f"https://signed/gallery/{story_id}/1.jpg?exp=3600"
    assert listed[3]["image"] is None


def test_delete_removes_the_gallery_images(env):
    session_id = finished_session(env)
    env["images"][(session_id, 1)] = {"status": "ready", "key": f"sessions/{session_id}/1.jpg"}
    env["s3"].objects[f"sessions/{session_id}/1.jpg"] = (JPEG, {})
    result = gallery.publish(session_id, True)
    gallery.delete(result["story_id"], result["delete_token"])
    assert env["s3"].deleted == [f"gallery/{result['story_id']}/1.jpg"]
    assert env["stories"] == {}


def test_delete_succeeds_even_if_the_s3_delete_fails(env, monkeypatch):
    session_id = finished_session(env)
    env["images"][(session_id, 1)] = {"status": "ready", "key": f"sessions/{session_id}/1.jpg"}
    env["s3"].objects[f"sessions/{session_id}/1.jpg"] = (JPEG, {})
    result = gallery.publish(session_id, True)

    def boom(**kwargs):
        raise RuntimeError("s3")

    monkeypatch.setattr(env["s3"], "delete_objects", boom)
    assert gallery.delete(result["story_id"], result["delete_token"]) == {"status": "deleted"}


def test_images_status_rejects_non_string_session():
    with pytest.raises(ApiError) as error:
        images.status(None)
    assert error.value.status == 404


# --- DynamoDB (tabla falsa) ---------------------------------------------------------------


class FakeTable:
    def __init__(self):
        self.puts = []

    def put_item(self, **kwargs):
        self.puts.append(kwargs)

    def get_item(self, **kwargs):
        self.key = kwargs["Key"]
        return {"Item": {"status": "ready"}}


def test_image_items_use_their_own_key_and_a_ttl(monkeypatch):
    table = FakeTable()
    monkeypatch.setattr(db, "table", table)
    db.put_image("s1", 4, "ready", "sessions/s1/4.jpg")
    item = table.puts[0]["Item"]
    assert item["pk"] == "IMAGE#s1#4" and item["status"] == "ready"
    assert item["key"] == "sessions/s1/4.jpg" and item["ttl"] > 0
    assert db.get_image("s1", 4) == {"status": "ready"} and table.key == {"pk": "IMAGE#s1#4"}
