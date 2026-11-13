import re
from pathlib import Path

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.guardrail import SELF_HARM_TOPIC
from stacks.nightmare_stack import NightmareStack

BACKEND_MODERATION = (
    Path(__file__).parents[2] / "backend" / "src" / "nightmare" / "moderation.py"
)


def template() -> Template:
    app = cdk.App()
    stack = NightmareStack(app, "Test", env=cdk.Environment(region="eu-south-2"))
    return Template.from_stack(stack)


def test_self_harm_topic_name_matches_the_backend():
    backend = re.search(r'SELF_HARM_TOPIC = "(\w+)"', BACKEND_MODERATION.read_text("utf-8"))

    assert backend and backend.group(1) == SELF_HARM_TOPIC
    template().has_resource_properties(
        "AWS::Bedrock::Guardrail",
        {
            "TopicPolicyConfig": {
                "TopicsConfig": [Match.object_like({"Name": SELF_HARM_TOPIC, "Type": "DENY"})]
            }
        },
    )


def test_filters_are_calibrated_for_nightmares():
    filters = template().find_resources("AWS::Bedrock::Guardrail")
    (guardrail,) = filters.values()
    by_type = {
        f["Type"]: f for f in guardrail["Properties"]["ContentPolicyConfig"]["FiltersConfig"]
    }

    assert by_type["VIOLENCE"]["InputStrength"] == "LOW"
    assert by_type["SEXUAL"] == {"Type": "SEXUAL", "InputStrength": "HIGH", "OutputStrength": "HIGH"}
    assert by_type["PROMPT_ATTACK"]["OutputStrength"] == "NONE"


def test_a_published_version_is_exported():
    t = template()
    t.resource_count_is("AWS::Bedrock::GuardrailVersion", 1)
    t.has_output("GuardrailId", {})
    t.has_output("GuardrailVersion", {})
