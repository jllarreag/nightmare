import pytest
from pydantic import ValidationError

from factories import step_dict
from nightmare.models import Category, Classification, Step


@pytest.mark.parametrize("step", [1, 2, 3, 4, 5])
def test_every_step_of_the_arc_is_valid(step):
    assert Step.model_validate(step_dict(step)).step == step


def test_technique_must_match_the_fixed_arc():
    with pytest.raises(ValidationError, match="must use technique 'recreate'"):
        Step.model_validate(step_dict(1, technique="rewrite"))


def test_narration_word_limit():
    with pytest.raises(ValidationError, match="at most 120 words"):
        Step.model_validate(step_dict(2, narration="word " * 121))


@pytest.mark.parametrize("choices", [[], [{"id": "a", "label": "Only one"}]])
def test_steps_before_closing_need_two_or_three_choices(choices):
    with pytest.raises(ValidationError, match="2 or 3 choices"):
        Step.model_validate(step_dict(3, choices=choices))


def test_choice_ids_must_be_unique():
    duplicated = [{"id": "a", "label": "One"}, {"id": "a", "label": "Two"}]
    with pytest.raises(ValidationError, match="unique"):
        Step.model_validate(step_dict(2, choices=duplicated))


def test_closing_step_has_no_choices_and_needs_learning_and_tip():
    with pytest.raises(ValidationError, match="must not have choices"):
        Step.model_validate(step_dict(5, choices=[{"id": "a", "label": "x"}]))
    with pytest.raises(ValidationError, match="learning and a coping tip"):
        Step.model_validate(step_dict(5, coping_tip=None))


@pytest.mark.parametrize("step", [1, 4])
def test_image_steps_require_an_image_prompt(step):
    with pytest.raises(ValidationError, match="needs an image_prompt"):
        Step.model_validate(step_dict(step, image_prompt=None))


def test_image_prompt_is_dropped_on_steps_without_image():
    step = Step.model_validate(step_dict(2, image_prompt="unexpected scene"))

    assert step.image_prompt is None


def test_only_ok_classification_is_allowed():
    assert Classification(category=Category.OK).allowed
    for category in (Category.NOT_SERIOUS, Category.FORBIDDEN_CONTENT, Category.RISK):
        assert not Classification(category=category).allowed
