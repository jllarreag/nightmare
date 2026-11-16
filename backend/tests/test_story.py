import pytest

from factories import step_dict
from nightmare.bedrock import ModelOutputError
from nightmare.models import Category, Classification, Step, StoryOpening
from nightmare.story import (
    SESSION_TTL_SECONDS,
    InvalidRequest,
    SessionFinished,
    SessionNotFound,
    StoryService,
)

NOW = 1_800_000_000
SESSION_ID = "f" * 32
NIGHTMARE = "Sueño que una sombra me persigue por un bosque oscuro."


class FakeNova:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def converse_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.results.pop(0)


class FakeModerator:
    def __init__(self, category=Category.OK, output_ok=True):
        self.category = category
        self.output_ok = output_ok
        self.classified = []
        self.checked = []

    def classify(self, text):
        self.classified.append(text)
        return Classification(category=self.category)

    def check_output(self, text):
        self.checked.append(text)
        return self.output_ok


class FakeStore:
    def __init__(self):
        self.sessions = {}
        self.advanced = []
        self.deleted = []

    def create(self, session):
        self.sessions[session.id] = session.model_copy(deep=True)

    def get(self, session_id):
        found = self.sessions.get(session_id)
        return found.model_copy(deep=True) if found else None

    def advance(self, session, expected_index):
        self.advanced.append(expected_index)
        self.sessions[session.id] = session.model_copy(deep=True)

    def delete(self, session_id):
        self.deleted.append(session_id)
        self.sessions.pop(session_id, None)


def opening():
    return StoryOpening(
        character_bible="a slender adult",
        summary="una sombra persigue al soñador",
        step=Step.model_validate(step_dict(1)),
    )


def service(nova, moderator=None, store=None):
    return StoryService(
        nova,
        moderator or FakeModerator(),
        store or FakeStore(),
        clock=lambda: NOW,
        new_id=lambda: SESSION_ID,
    )


def started(nova, moderator=None):
    store = FakeStore()
    svc = service(FakeNova(opening(), *nova.results), moderator, store)
    svc.start(NIGHTMARE, "es")
    return svc, store


# --- start ---------------------------------------------------------------------------------


def test_start_creates_session_and_returns_public_step():
    store = FakeStore()
    nova = FakeNova(opening())

    result = service(nova, store=store).start(f"  {NIGHTMARE}  ", "es")

    assert result["status"] == "ok"
    assert result["session_id"] == SESSION_ID
    assert result["step"]["step"] == 1
    assert result["step"]["has_image"] is True
    assert "image_prompt" not in result["step"]
    saved = store.sessions[SESSION_ID]
    assert saved.step_index == 1
    assert saved.ttl == NOW + SESSION_TTL_SECONDS
    assert "Spanish" in nova.calls[0]["system"]


def test_raw_nightmare_is_never_stored():
    store = FakeStore()

    service(FakeNova(opening()), store=store).start(NIGHTMARE, "es")

    assert NIGHTMARE not in store.sessions[SESSION_ID].model_dump_json()


@pytest.mark.parametrize("text", ["corto", "x" * 2001, "   " + "a" * 10 + "   "])
def test_start_rejects_bad_length_without_calling_models(text):
    nova, moderator = FakeNova(), FakeModerator()

    with pytest.raises(InvalidRequest, match="nightmare_length"):
        service(nova, moderator).start(text, "es")
    assert nova.calls == [] and moderator.classified == []


@pytest.mark.parametrize(
    "category", [Category.NOT_SERIOUS, Category.FORBIDDEN_CONTENT, Category.RISK]
)
def test_start_stops_on_moderation_and_stores_nothing(category):
    store, nova = FakeStore(), FakeNova()

    result = service(nova, FakeModerator(category), store).start(NIGHTMARE, "en")

    assert result["status"] == "stopped"
    assert result["category"] == category.value
    assert nova.calls == [] and store.sessions == {}


def test_risk_stop_includes_help_resources():
    result = service(FakeNova(), FakeModerator(Category.RISK)).start(NIGHTMARE, "es")

    assert [r["contact"] for r in result["resources"]][:2] == ["024", "112"]


def test_start_stops_when_generated_text_is_unsafe():
    store = FakeStore()

    result = service(FakeNova(opening()), FakeModerator(output_ok=False), store).start(
        NIGHTMARE, "es"
    )

    assert (result["status"], result["category"]) == ("stopped", "forbidden_content")
    assert store.sessions == {}


# --- next ----------------------------------------------------------------------------------


def test_next_generates_the_following_step_with_the_chosen_label():
    svc, store = started(FakeNova(Step.model_validate(step_dict(2))))

    result = svc.next(SESSION_ID, "b")

    assert result["step"]["step"] == 2 and result["finished"] is False
    assert result["step"]["has_image"] is False
    saved = store.sessions[SESSION_ID]
    assert saved.step_index == 2 and saved.chosen == ["b"]
    assert store.advanced == [1]


def test_full_story_reaches_the_closing_with_reasoning_only_at_the_end():
    steps = [Step.model_validate(step_dict(n)) for n in (2, 3, 4, 5)]
    nova = FakeNova(opening(), *steps)
    svc = service(nova)
    svc.start(NIGHTMARE, "es")

    results = [svc.next(SESSION_ID, "a") for _ in steps]

    assert [r["step"]["step"] for r in results] == [2, 3, 4, 5]
    assert results[-1]["finished"] is True
    assert results[-1]["step"]["learning"]
    assert [call.get("reasoning") for call in nova.calls] == [None, None, None, None, "low"]
    with pytest.raises(SessionFinished):
        svc.next(SESSION_ID, "a")


def test_next_rejects_unknown_session_and_unknown_choice():
    svc, _ = started(FakeNova())

    with pytest.raises(SessionNotFound):
        svc.next("0" * 32, "a")
    with pytest.raises(InvalidRequest, match="choice"):
        svc.next(SESSION_ID, "z")


def test_next_rejects_a_step_with_the_wrong_number():
    svc, store = started(FakeNova(Step.model_validate(step_dict(3))))

    with pytest.raises(ModelOutputError):
        svc.next(SESSION_ID, "a")
    assert store.sessions[SESSION_ID].step_index == 1


def test_next_ends_and_deletes_the_session_when_output_is_unsafe():
    moderator = FakeModerator()
    svc, store = started(FakeNova(Step.model_validate(step_dict(2))), moderator)
    moderator.output_ok = False

    result = svc.next(SESSION_ID, "a")

    assert result["status"] == "stopped"
    assert store.deleted == [SESSION_ID] and store.sessions == {}
