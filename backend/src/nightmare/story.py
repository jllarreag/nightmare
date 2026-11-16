"""Story engine: starts a session from a nightmare and advances it step by step.

This module has no AWS or HTTP code. It receives its collaborators (Nova, moderator, store), so
it can be tested with fakes and reused by every Lambda handler.
"""

import time
import uuid
from collections.abc import Callable
from typing import Any

from nightmare import prompts
from nightmare.bedrock import ModelOutputError, NovaClient
from nightmare.messages import stop_message
from nightmare.models import (
    IMAGE_STEPS,
    TOTAL_STEPS,
    Category,
    Language,
    Session,
    Step,
    StoryOpening,
)
from nightmare.moderation import Moderator
from nightmare.store import SessionStore

SESSION_TTL_SECONDS = 24 * 60 * 60
MIN_NIGHTMARE_CHARS = 20
MAX_NIGHTMARE_CHARS = 2000


class InvalidRequest(Exception):
    """The request is malformed. `code` is returned to the frontend, which localizes it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SessionNotFound(Exception):
    pass


class SessionFinished(Exception):
    pass


def public_step(step: Step) -> dict[str, Any]:
    """What the frontend receives. The image prompt is internal and is not exposed."""
    data = step.model_dump(mode="json", exclude={"image_prompt"})
    data["has_image"] = step.step in IMAGE_STEPS
    return data


def step_text(step: Step) -> str:
    """All user-facing text of a step, for the output guardrail."""
    parts = [step.title, step.narration, *(c.label for c in step.choices)]
    parts += [part for part in (step.learning, step.coping_tip) if part]
    return "\n".join(parts)


def _stopped(category: Category, language: Language) -> dict[str, Any]:
    return {"status": "stopped", **stop_message(category, language)}


class StoryService:
    def __init__(
        self,
        nova: NovaClient,
        moderator: Moderator,
        store: SessionStore,
        clock: Callable[[], float] = time.time,
        new_id: Callable[[], str] = lambda: uuid.uuid4().hex,
    ) -> None:
        self._nova = nova
        self._moderator = moderator
        self._store = store
        self._clock = clock
        self._new_id = new_id

    def start(self, nightmare: str, language: Language) -> dict[str, Any]:
        text = nightmare.strip()
        if not MIN_NIGHTMARE_CHARS <= len(text) <= MAX_NIGHTMARE_CHARS:
            raise InvalidRequest("nightmare_length")

        classification = self._moderator.classify(text)
        if not classification.allowed:
            return _stopped(classification.category, language)

        opening = self._nova.converse_json(
            system=prompts.story_system(language),
            user=prompts.opening_user(text),
            schema=StoryOpening,
        )
        if not self._moderator.check_output(step_text(opening.step)):
            return _stopped(Category.FORBIDDEN_CONTENT, language)

        session = Session(
            id=self._new_id(),
            language=language,
            step_index=1,
            summary=opening.summary,
            character_bible=opening.character_bible,
            history=[opening.step],
            ttl=int(self._clock()) + SESSION_TTL_SECONDS,
        )
        self._store.create(session)
        return {"status": "ok", "session_id": session.id, "step": public_step(opening.step)}

    def next(self, session_id: str, choice_id: str) -> dict[str, Any]:
        session = self._store.get(session_id)
        if session is None:
            raise SessionNotFound(session_id)
        if session.step_index >= TOTAL_STEPS:
            raise SessionFinished(session_id)

        # Choices are buttons, not free text: validating the id is the moderation of the choice.
        current = session.history[-1]
        choice = next((c for c in current.choices if c.id == choice_id), None)
        if choice is None:
            raise InvalidRequest("choice")

        target = session.step_index + 1
        closing = target == TOTAL_STEPS
        step = self._nova.converse_json(
            system=prompts.story_system(session.language),
            user=prompts.next_step_user(session.summary, session.history, choice.label, target),
            schema=Step,
            # The closing carries the learning, so it gets extended thinking (steering tech.md).
            reasoning="low" if closing else None,
            max_tokens=3000 if closing else 1500,
        )
        if step.step != target:
            raise ModelOutputError(f"expected step {target}, got {step.step}")

        if not self._moderator.check_output(step_text(step)):
            self._store.delete(session.id)
            return _stopped(Category.FORBIDDEN_CONTENT, session.language)

        session.history.append(step)
        session.chosen.append(choice.id)
        session.step_index = target
        self._store.advance(session, expected_index=target - 1)
        return {
            "status": "ok",
            "session_id": session.id,
            "step": public_step(step),
            "finished": closing,
        }
