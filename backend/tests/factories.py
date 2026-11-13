"""Builders for valid test data."""

from typing import Any

from nightmare.models import IMAGE_STEPS, STEP_TECHNIQUES, TOTAL_STEPS


def step_dict(step: int = 1, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "step": step,
        "title": f"Step {step}",
        "narration": "You walk through a quiet corridor and the fog slowly fades.",
        "choices": [{"id": "a", "label": "Open the door"}, {"id": "b", "label": "Breathe"}],
        "image_prompt": "a figure in a foggy corridor" if step in IMAGE_STEPS else None,
        "technique": STEP_TECHNIQUES[step].value,
        "learning": None,
        "coping_tip": None,
    }
    if step == TOTAL_STEPS:
        data.update(
            choices=[],
            learning="Fear shrinks when you face it.",
            coping_tip="Rehearse the new ending for five minutes before sleeping.",
        )
    data.update(overrides)
    return data
