import json

import pytest

from factories import step_dict
from nightmare.bedrock import ModelOutputError, NovaClient, extract_text, parse_json
from nightmare.models import Classification, Step

MODEL_ID = "eu.amazon.nova-2-lite-v1:0"


def response(*blocks):
    return {"output": {"message": {"role": "assistant", "content": list(blocks)}}}


class FakeBedrock:
    """Records converse calls and returns queued responses."""

    def __init__(self, *texts):
        self.calls = []
        self._texts = list(texts)

    def converse(self, **request):
        self.calls.append(request)
        return response({"text": self._texts.pop(0)})


def test_extract_text_skips_reasoning_blocks():
    result = response(
        {"reasoningContent": {"reasoningText": {"text": "[REDACTED]"}}},
        {"text": '{"category": "ok"}'},
    )

    assert extract_text(result) == '{"category": "ok"}'


def test_parse_json_tolerates_fences_and_prose():
    text = 'Here it is:\n```json\n{"category": "risk", "reason": "x"}\n```'

    assert parse_json(text, Classification).category == "risk"


def test_converse_json_returns_validated_model_and_sends_config():
    bedrock = FakeBedrock(json.dumps(step_dict(1)))

    step = NovaClient(bedrock, MODEL_ID).converse_json(
        system="sys", user="dream", schema=Step, temperature=0.5
    )

    assert step.step == 1
    request = bedrock.calls[0]
    assert request["modelId"] == MODEL_ID
    assert request["system"] == [{"text": "sys"}]
    assert request["inferenceConfig"]["temperature"] == 0.5
    assert "additionalModelRequestFields" not in request


def test_reasoning_is_sent_only_when_requested():
    bedrock = FakeBedrock('{"category": "ok"}')

    NovaClient(bedrock, MODEL_ID).converse_json(
        system="s", user="u", schema=Classification, reasoning="low"
    )

    assert bedrock.calls[0]["additionalModelRequestFields"] == {
        "reasoningConfig": {"type": "enabled", "maxReasoningEffort": "low"}
    }


def test_retries_once_with_the_error_as_feedback():
    bedrock = FakeBedrock("not json at all", '{"category": "not_serious"}')

    result = NovaClient(bedrock, MODEL_ID).converse_json(
        system="s", user="u", schema=Classification
    )

    assert result.category == "not_serious"
    assert len(bedrock.calls) == 2
    retry_messages = bedrock.calls[1]["messages"]
    assert retry_messages[1]["role"] == "assistant"
    assert "not valid" in retry_messages[2]["content"][0]["text"]


def test_raises_after_two_invalid_outputs():
    bedrock = FakeBedrock('{"category": "unknown"}', "still wrong")

    with pytest.raises(ModelOutputError):
        NovaClient(bedrock, MODEL_ID).converse_json(system="s", user="u", schema=Classification)
    assert len(bedrock.calls) == 2
