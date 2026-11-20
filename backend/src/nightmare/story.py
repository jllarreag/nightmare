"""Lógica de la historia: empezar una sesión y avanzar paso a paso."""

import uuid

from nightmare import ai, db, prompts, safety
from nightmare.messages import stop_message
from nightmare.models import TOTAL_STEPS, ApiError, Category, Session, Step

MIN_CHARS, MAX_CHARS = 20, 2000


def stopped(category: Category, language: str) -> dict:
    """Respuesta cuando la sesión termina por seguridad (se guarda nada)."""
    return {"status": "stopped", **stop_message(category, language)}


def parse_opening(data: dict) -> tuple[str, Step]:
    return str(data["summary"]), Step.from_dict(data["step"])


def start(nightmare, language) -> dict:
    if language not in ("es", "en"):
        raise ApiError(400, "language")
    if not isinstance(nightmare, str) or not MIN_CHARS <= len(nightmare.strip()) <= MAX_CHARS:
        raise ApiError(400, "nightmare_length")
    text = nightmare.strip()

    category = safety.classify(text)
    if category != Category.OK:
        return stopped(category, language)

    summary, step = ai.ask(
        prompts.story_system(language), prompts.opening_user(text), parse=parse_opening
    )
    if not safety.output_is_safe(step.text()):
        return stopped(Category.FORBIDDEN_CONTENT, language)

    # Solo se guarda el resumen anónimo, nunca el texto original.
    session = Session(id=uuid.uuid4().hex, language=language, summary=summary, history=[step])
    db.save(session)
    return {"status": "ok", "session_id": session.id, "step": step.public()}


def next_step(session_id, choice_id) -> dict:
    session = db.load(session_id) if isinstance(session_id, str) else None
    if session is None:
        raise ApiError(404, "session_not_found")
    if session.step_index >= TOTAL_STEPS:
        raise ApiError(409, "session_finished")

    # Las opciones son botones, no texto libre: validar el id ya es moderar la elección.
    choice = next((c for c in session.history[-1].choices if c.id == choice_id), None)
    if choice is None:
        raise ApiError(400, "choice")

    target = session.step_index + 1
    closing = target == TOTAL_STEPS

    def parse(data: dict) -> Step:
        step = Step.from_dict(data)
        if step.step != target:
            raise ValueError(f"expected step {target}")
        return step

    step = ai.ask(
        prompts.story_system(session.language),
        prompts.next_step_user(session.summary, session.history, choice.label, target),
        parse=parse,
        # El cierre lleva el aprendizaje: razonamiento extendido (steering tech.md).
        reasoning="low" if closing else None,
        max_tokens=3000 if closing else 1500,
    )
    if not safety.output_is_safe(step.text()):
        db.delete(session.id)
        return stopped(Category.FORBIDDEN_CONTENT, session.language)

    session.history.append(step)
    session.chosen.append(choice.id)
    db.save(session)
    return {"status": "ok", "session_id": session.id, "step": step.public(), "finished": closing}
