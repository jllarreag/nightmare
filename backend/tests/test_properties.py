"""Property-based tests (Hypothesis) for the story contract and safety messages.

They generate many random steps and sessions to check the invariants of the 5-step arc,
instead of a few hand-written examples.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nightmare.messages import stop_message
from nightmare.models import (
    IMAGE_STEPS,
    MAX_NARRATION_WORDS,
    TECHNIQUES,
    TOTAL_STEPS,
    Category,
    Session,
    Step,
)

text = st.text(min_size=1, max_size=40).filter(lambda s: s.strip())
word = st.text(alphabet=st.characters(categories=["L"]), min_size=1, max_size=8)


@st.composite
def narration(draw, min_words=1, max_words=MAX_NARRATION_WORDS):
    return " ".join(draw(st.lists(word, min_size=min_words, max_size=max_words)))


@st.composite
def choices(draw, min_size=2, max_size=3):
    ids = draw(
        st.lists(st.text(min_size=1, max_size=3), min_size=min_size, max_size=max_size, unique=True)
    )
    return [{"id": i, "label": draw(text)} for i in ids]


@st.composite
def valid_step(draw, number=None):
    n = number or draw(st.integers(1, TOTAL_STEPS))
    closing = n == TOTAL_STEPS
    return {
        "step": n,
        "title": draw(text),
        "narration": draw(narration()),
        "technique": TECHNIQUES[n],
        "choices": [] if closing else draw(choices()),
        "image_prompt": draw(text) if n in IMAGE_STEPS else draw(st.none() | text),
        "learning": draw(text) if closing else None,
        "coping_tip": draw(text) if closing else None,
    }


@given(valid_step())
def test_valid_steps_are_accepted_and_hide_the_image_prompt(data):
    step = Step.from_dict(data)
    public = step.public()
    assert "image_prompt" not in public
    assert public["has_image"] == (step.step in IMAGE_STEPS)
    if step.step not in IMAGE_STEPS:
        assert step.image_prompt is None


@given(valid_step(), st.sampled_from(sorted(set(TECHNIQUES.values()))))
def test_each_step_number_only_accepts_its_technique(data, technique):
    data["technique"] = technique
    if technique == TECHNIQUES[data["step"]]:
        Step.from_dict(data)
    else:
        with pytest.raises(ValueError):
            Step.from_dict(data)


@given(valid_step(number=TOTAL_STEPS), choices(min_size=1))
def test_closing_step_never_has_choices(data, extra):
    data["choices"] = extra
    with pytest.raises(ValueError):
        Step.from_dict(data)


@given(valid_step(number=TOTAL_STEPS), st.sampled_from(["learning", "coping_tip"]))
def test_closing_step_needs_learning_and_coping_tip(data, missing):
    data[missing] = None
    with pytest.raises(ValueError):
        Step.from_dict(data)


@given(st.integers(1, TOTAL_STEPS - 1).flatmap(valid_step), st.sampled_from([0, 1, 4, 5]))
def test_steps_before_closing_need_two_or_three_choices(data, count):
    data["choices"] = [{"id": str(i), "label": "x"} for i in range(count)]
    with pytest.raises(ValueError):
        Step.from_dict(data)


@given(
    valid_step(), narration(min_words=MAX_NARRATION_WORDS + 1, max_words=MAX_NARRATION_WORDS + 30)
)
def test_narration_over_the_word_limit_is_rejected(data, long_narration):
    data["narration"] = long_narration
    with pytest.raises(ValueError):
        Step.from_dict(data)


@given(
    st.lists(st.integers(1, TOTAL_STEPS - 1), min_size=0, max_size=TOTAL_STEPS - 1).flatmap(
        lambda ns: st.tuples(*[valid_step(number=n) for n in ns])
    ),
    st.text(max_size=200),
    st.sampled_from(["es", "en"]),
)
def test_session_survives_a_json_round_trip(steps, summary, language):
    history = [Step.from_dict(s) for s in steps]
    session = Session(id="s", language=language, summary=summary, history=history)
    assert Session.from_json(session.to_json()) == session


@given(
    st.sampled_from([c for c in Category if c != Category.OK]),
    st.sampled_from(["es", "en"]),
)
def test_only_risk_stops_show_help_resources(category, language):
    payload = stop_message(category, language)
    assert payload["message"]
    if category == Category.RISK:
        contacts = {r["contact"] for r in payload["resources"]}
        assert {"024", "112"} <= contacts
    else:
        assert payload["resources"] == []
