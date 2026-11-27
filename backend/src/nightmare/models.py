"""Datos de la app: constantes del arco, Step, Session y el error de API.

Sin pydantic: cada clase es un dataclass y `Step.from_dict` valida lo que devuelve el modelo.
"""

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Literal

Language = Literal["es", "en"]

TOTAL_STEPS = 5
MAX_NARRATION_WORDS = 120
IMAGE_STEPS = (1, 4)  # solo la pesadilla (1) y el final reescrito (4) llevan imagen

# El arco es fijo: número de paso -> técnica
TECHNIQUES = {1: "recreate", 2: "control", 3: "decision", 4: "rewrite", 5: "closing"}


class Category(StrEnum):
    OK = "ok"
    NOT_SERIOUS = "not_serious"
    FORBIDDEN_CONTENT = "forbidden_content"
    RISK = "risk"


class ApiError(Exception):
    """Error que se devuelve al frontend como {"error": code} con el status HTTP indicado."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass
class Choice:
    id: str
    label: str


@dataclass
class Step:
    step: int
    title: str
    narration: str
    technique: str
    choices: list[Choice] = field(default_factory=list)
    image_prompt: str | None = None
    learning: str | None = None
    coping_tip: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Step":
        """Valida el JSON del modelo. Lanza ValueError/KeyError/TypeError si no cumple."""
        step = cls(
            step=int(data["step"]),
            title=str(data["title"]),
            narration=str(data["narration"]),
            technique=str(data["technique"]),
            choices=[Choice(str(c["id"]), str(c["label"])) for c in data.get("choices") or []],
            image_prompt=data.get("image_prompt") or None,
            learning=data.get("learning") or None,
            coping_tip=data.get("coping_tip") or None,
        )
        step.check()
        return step

    def check(self) -> None:
        if self.step not in TECHNIQUES:
            raise ValueError(f"step must be 1..{TOTAL_STEPS}")
        if self.technique != TECHNIQUES[self.step]:
            raise ValueError(f"step {self.step} must use technique '{TECHNIQUES[self.step]}'")
        if not self.title or not self.narration:
            raise ValueError("title and narration are required")
        if len(self.narration.split()) > MAX_NARRATION_WORDS:
            raise ValueError(f"narration must have at most {MAX_NARRATION_WORDS} words")
        if self.step == TOTAL_STEPS:
            if self.choices:
                raise ValueError("the closing step must not have choices")
            if not (self.learning and self.coping_tip):
                raise ValueError("the closing step needs learning and coping_tip")
        else:
            if not 2 <= len(self.choices) <= 3:
                raise ValueError("steps before the closing need 2 or 3 choices")
            if len({c.id for c in self.choices}) != len(self.choices):
                raise ValueError("choice ids must be unique")
        if self.step in IMAGE_STEPS and not self.image_prompt:
            raise ValueError(f"step {self.step} needs an image_prompt")
        if self.step not in IMAGE_STEPS:
            self.image_prompt = None

    def text(self) -> str:
        """Todo el texto visible del paso (para pasarlo por el guardrail de salida)."""
        parts = [self.title, self.narration, *(c.label for c in self.choices)]
        return "\n".join(parts + [p for p in (self.learning, self.coping_tip) if p])

    def public(self) -> dict[str, Any]:
        """Lo que recibe el frontend: sin image_prompt (interno)."""
        data = asdict(self)
        del data["image_prompt"]
        data["has_image"] = self.step in IMAGE_STEPS
        return data


@dataclass
class Session:
    id: str
    language: Language
    summary: str  # resumen anónimo; el texto original de la pesadilla nunca se guarda
    history: list[Step] = field(default_factory=list)
    chosen: list[str] = field(default_factory=list)
    published: bool = False  # ya se publicó en la galería (solo una vez por sesión)

    character: str = ""  # descripcion generica del personaje, comun a las imagenes

    @property
    def step_index(self) -> int:
        return len(self.history)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "Session":
        data = json.loads(raw)
        data["history"] = [Step.from_dict(s) for s in data["history"]]
        return cls(**data)
