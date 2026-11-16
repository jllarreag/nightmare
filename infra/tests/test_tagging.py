import pytest

from helpers import template
from stacks.tagging import APP_TAGS

# Resource types that must carry the tag. If one is missing, its cost would be unattributed.
MUST_BE_TAGGED = {
    "AWS::Bedrock::ApplicationInferenceProfile",
    "AWS::Bedrock::Guardrail",
    "AWS::DynamoDB::Table",
    "AWS::Lambda::Function",
    "AWS::IAM::Role",
    "AWS::Logs::LogGroup",
    "AWS::ApiGatewayV2::Api",
    "AWS::ApiGatewayV2::Stage",
}


def tags_of(properties: dict) -> dict[str, str]:
    tags = properties.get("Tags")
    if isinstance(tags, dict):  # API Gateway v2 uses a map
        return tags
    return {tag["Key"]: tag["Value"] for tag in tags or []}


@pytest.fixture(scope="module")
def resources():
    return template().to_json()["Resources"]


def test_every_cost_relevant_resource_has_the_app_tag(resources):
    found_types = {r["Type"] for r in resources.values()}
    assert MUST_BE_TAGGED <= found_types

    for logical_id, resource in resources.items():
        if resource["Type"] in MUST_BE_TAGGED:
            tags = tags_of(resource.get("Properties", {}))
            for key, value in APP_TAGS.items():
                assert tags.get(key) == value, f"{logical_id} ({resource['Type']}) is not tagged"


def test_no_resource_with_tags_misses_the_app_tag(resources):
    for logical_id, resource in resources.items():
        properties = resource.get("Properties", {})
        if "Tags" in properties:
            assert tags_of(properties).get("application") == "nightmare", logical_id
