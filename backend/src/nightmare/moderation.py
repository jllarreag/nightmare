"""Layered moderation: Bedrock Guardrails, Nova classifier and image prompt sanitizing.

Rules (see .kiro/steering/safety.md):
- `risk` always wins and is never downgraded: a person in crisis must get support, not a refusal.
- Rejections (`not_serious`, `forbidden_content`) are double-checked with extended thinking,
  so genuine but dark nightmares are not discarded.
- Nothing here logs user text; only categories and policy names.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from nightmare import prompts
from nightmare.bedrock import NovaClient
from nightmare.models import Category, Classification, VisualPrompt

logger = logging.getLogger(__name__)

GuardrailSource = Literal["INPUT", "OUTPUT"]

# Name of the denied topic defined in the guardrail (infra GuardrailStack).
SELF_HARM_TOPIC = "SelfHarm"

# Last deterministic layer for image prompts, which go to models without Guardrails support.
_IMAGE_DENYLIST = re.compile(
    r"\b(blood\w*|gor[ey]|gory|corpse\w*|dead bod\w*|decapitat\w*|dismember\w*|mutilat\w*|"
    r"nud\w*|naked|nsfw|sex\w*|erotic\w*|suicid\w*|self[- ]harm|weapon\w*|gun\w*|knife|knives|"
    r"sangre|cad[aá]ver\w*|desnud\w*|sexual\w*)\b",
    re.IGNORECASE,
)


_NEGATION = re.compile(r"\b(?:no|without|sin)\s+[\w-]+", re.IGNORECASE)


def _scene_only(prompt: str) -> str:
    """Drop the style suffix if the model added it anyway; we always append our own."""
    head, _, _ = prompt.partition(prompts.IMAGE_STYLE_SUFFIX.split(",")[0])
    return head.strip().rstrip(",. ").strip()


def _without_negations(text: str) -> str:
    """'no gore' or 'without blood' must not trip the denylist."""
    return _NEGATION.sub(" ", text)


@dataclass(frozen=True)
class GuardrailResult:
    intervened: bool
    category: Category | None = None
    policies: tuple[str, ...] = ()


class Guardrail:
    """Wraps ApplyGuardrail. Disabled (always passes) when no guardrail id is configured."""

    def __init__(self, client: Any, guardrail_id: str, version: str) -> None:
        self._client = client
        self._id = guardrail_id
        self._version = version

    @property
    def enabled(self) -> bool:
        return bool(self._id)

    def check(self, text: str, source: GuardrailSource) -> GuardrailResult:
        if not self.enabled:
            return GuardrailResult(intervened=False)

        response = self._client.apply_guardrail(
            guardrailIdentifier=self._id,
            guardrailVersion=self._version,
            source=source,
            content=[{"text": {"text": text}}],
        )
        if response.get("action") != "GUARDRAIL_INTERVENED":
            return GuardrailResult(intervened=False)

        policies = _blocked_policies(response.get("assessments", []))
        category = _category_for(policies)
        logger.info("guardrail intervened", extra={"source": source, "policies": policies})
        return GuardrailResult(intervened=True, category=category, policies=policies)


def _blocked_policies(assessments: list[dict[str, Any]]) -> tuple[str, ...]:
    blocked: list[str] = []
    for assessment in assessments:
        for topic in assessment.get("topicPolicy", {}).get("topics", []):
            if topic.get("action") == "BLOCKED":
                blocked.append(f"topic:{topic.get('name')}")
        for item in assessment.get("contentPolicy", {}).get("filters", []):
            if item.get("action") == "BLOCKED":
                blocked.append(f"content:{item.get('type')}")
        word_policy = assessment.get("wordPolicy", {})
        if any(
            word.get("action") == "BLOCKED"
            for key in ("customWords", "managedWordLists")
            for word in word_policy.get(key, [])
        ):
            blocked.append("word")
    return tuple(blocked)


def _category_for(policies: tuple[str, ...]) -> Category:
    if f"topic:{SELF_HARM_TOPIC}" in policies:
        return Category.RISK
    if "content:PROMPT_ATTACK" in policies:
        return Category.NOT_SERIOUS
    return Category.FORBIDDEN_CONTENT


class Moderator:
    def __init__(self, nova: NovaClient, guardrail: Guardrail) -> None:
        self._nova = nova
        self._guardrail = guardrail

    def classify(self, text: str) -> Classification:
        """Classify user text. The session may only continue when the result is `ok`."""
        guard = self._guardrail.check(text, "INPUT")
        if guard.intervened and guard.category == Category.RISK:
            return Classification(category=Category.RISK, reason="guardrail self-harm topic")

        first = self._ask(text, reasoning=None)
        if guard.intervened:
            # The guardrail blocked it; the classifier can only upgrade the outcome to `risk`.
            if first.category == Category.RISK:
                return first
            return Classification(category=guard.category, reason="guardrail intervened")

        if first.category in (Category.OK, Category.RISK):
            return first

        # Possible false positive on a dark but genuine nightmare: think it through once more.
        second = self._ask(text, reasoning="low")
        logger.info(
            "classification rechecked",
            extra={"first": first.category.value, "second": second.category.value},
        )
        return second

    def check_output(self, text: str) -> bool:
        """True when generated text is safe to show."""
        return not self._guardrail.check(text, "OUTPUT").intervened

    def visual_prompt(self, character_bible: str, scene: str) -> str | None:
        """Return a safe, styled image prompt or None (the UI then shows a placeholder)."""
        result = self._nova.converse_json(
            system=prompts.VISUAL_PROMPT_SYSTEM,
            user=prompts.visual_prompt_user(character_bible, scene),
            schema=VisualPrompt,
            temperature=0.3,
            max_tokens=300,
        )
        if not result.safe:
            logger.info("visual prompt rejected", extra={"layer": "model"})
            return None
        scene = _scene_only(result.prompt)
        if not scene or _IMAGE_DENYLIST.search(_without_negations(scene)):
            logger.info("visual prompt rejected", extra={"layer": "denylist"})
            return None
        if self._guardrail.check(scene, "OUTPUT").intervened:
            logger.info("visual prompt rejected", extra={"layer": "guardrail"})
            return None
        return f"{scene}. {prompts.IMAGE_STYLE_SUFFIX}"

    def _ask(self, text: str, reasoning: Literal["low"] | None) -> Classification:
        return self._nova.converse_json(
            system=prompts.CLASSIFIER_SYSTEM,
            user=prompts.classifier_user(text),
            schema=Classification,
            temperature=0.0,
            max_tokens=1500 if reasoning else 200,
            reasoning=reasoning,
        )
