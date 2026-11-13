"""Pydantic schemas shared by every Lambda. They are the contract for model output too."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Language = Literal["es", "en"]

TOTAL_STEPS = 5
MAX_NARRATION_WORDS = 120
# Only the nightmare (step 1) and the rewritten, healing ending (step 4) get an image.
IMAGE_STEPS = frozenset({1, 4})


class Technique(StrEnum):
    RECREATE = "recreate"
    CONTROL = "control"
    DECISION = "decision"
    REWRITE = "rewrite"
    CLOSING = "closing"


# The arc is fixed: step number -> technique.
STEP_TECHNIQUES: dict[int, Technique] = {
    1: Technique.RECREATE,
    2: Technique.CONTROL,
    3: Technique.DECISION,
    4: Technique.REWRITE,
    5: Technique.CLOSING,
}


class Choice(BaseModel):
    id: str = Field(min_length=1, max_length=8)
    label: str = Field(min_length=1, max_length=160)


class Step(BaseModel):
    """One step of the story, exactly as the model must return it."""

    step: int = Field(ge=1, le=TOTAL_STEPS)
    title: str = Field(min_length=1, max_length=120)
    narration: str = Field(min_length=1)
    choices: list[Choice] = Field(default_factory=list)
    image_prompt: str | None = None
    technique: Technique
    learning: str | None = None
    coping_tip: str | None = None

    @field_validator("narration")
    @classmethod
    def narration_is_short(cls, value: str) -> str:
        if len(value.split()) > MAX_NARRATION_WORDS:
            raise ValueError(f"narration must have at most {MAX_NARRATION_WORDS} words")
        return value

    @model_validator(mode="after")
    def follows_the_arc(self) -> "Step":
        expected = STEP_TECHNIQUES[self.step]
        if self.technique != expected:
            raise ValueError(f"step {self.step} must use technique '{expected}'")

        if self.step == TOTAL_STEPS:
            if self.choices:
                raise ValueError("the closing step must not have choices")
            if not self.learning or not self.coping_tip:
                raise ValueError("the closing step needs a learning and a coping tip")
        elif not 2 <= len(self.choices) <= 3:
            raise ValueError("steps before the closing must have 2 or 3 choices")

        if len({choice.id for choice in self.choices}) != len(self.choices):
            raise ValueError("choice ids must be unique")

        if self.step in IMAGE_STEPS and not self.image_prompt:
            raise ValueError(f"step {self.step} needs an image_prompt")
        if self.step not in IMAGE_STEPS and self.image_prompt:
            # Not an error worth a retry: images are only generated for steps 1 and 4.
            self.image_prompt = None
        return self


class Category(StrEnum):
    OK = "ok"
    NOT_SERIOUS = "not_serious"
    FORBIDDEN_CONTENT = "forbidden_content"
    RISK = "risk"


class Classification(BaseModel):
    category: Category
    # Short internal reason. Never shown to the user and never logged with user text.
    reason: str = Field(default="", max_length=300)

    @property
    def allowed(self) -> bool:
        return self.category == Category.OK


class StoryOpening(BaseModel):
    """Output of the first generation: step 1 plus the sanitized character bible."""

    character_bible: str = Field(
        min_length=1,
        max_length=400,
        description="Generic visual description of the main character, no personal data",
    )
    summary: str = Field(
        min_length=1,
        max_length=600,
        description="Anonymized summary of the nightmare, used instead of the raw text",
    )
    step: Step


class VisualPrompt(BaseModel):
    """A sanitized image prompt: the only text that may leave the EU."""

    prompt: str = Field(min_length=1, max_length=600)
    safe: bool


class Session(BaseModel):
    id: str
    language: Language
    step_index: int = Field(ge=1, le=TOTAL_STEPS)
    summary: str
    character_bible: str
    history: list[Step] = Field(default_factory=list)
    chosen: list[str] = Field(default_factory=list)
    image_keys: dict[int, str] = Field(default_factory=dict)
    ttl: int


class GalleryItem(BaseModel):
    id: str
    title: str
    language: Language
    steps: list[Step]
    image_keys: dict[int, str] = Field(default_factory=dict)
    created_at: str
    delete_token_hash: str
