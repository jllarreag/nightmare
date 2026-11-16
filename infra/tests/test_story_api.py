import json

import pytest
from aws_cdk.assertions import Match

from helpers import template
from stacks.story_api import EU_PROFILE_REGIONS


@pytest.fixture(scope="module")
def t():
    return template()


def functions(t):
    return {
        props["Properties"]["Handler"]: props["Properties"]
        for props in t.find_resources("AWS::Lambda::Function").values()
    }


def statements(t):
    found = []
    for policy in t.find_resources("AWS::IAM::Policy").values():
        found += policy["Properties"]["PolicyDocument"]["Statement"]
    return found


def as_list(value):
    return value if isinstance(value, list) else [value]


def test_sessions_table_is_on_demand_with_ttl(t):
    t.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "BillingMode": "PAY_PER_REQUEST",
            "KeySchema": [{"AttributeName": "pk", "KeyType": "HASH"}],
            "TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True},
        },
    )


def test_two_arm_python_lambdas_with_the_backend_configuration(t):
    fns = functions(t)

    assert set(fns) == {
        "nightmare.handlers.start_session.handler",
        "nightmare.handlers.next_step.handler",
    }
    for props in fns.values():
        assert props["Runtime"] == "python3.12"
        assert props["Architectures"] == ["arm64"]
        assert props["Timeout"] == 29
        env = props["Environment"]["Variables"]
        # Nova is called through the tagged application inference profile.
        assert env["TEXT_MODEL_ID"]["Fn::GetAtt"][1] == "InferenceProfileArn"
        assert env["BASE_REGION"] == "eu-south-2"
        assert {"GUARDRAIL_ID", "GUARDRAIL_VERSION", "SESSIONS_TABLE"} <= set(env)


def test_bedrock_access_is_limited_to_nova_in_eu_regions(t):
    bedrock = [s for s in statements(t) if any("bedrock" in a for a in as_list(s["Action"]))]
    invoke = [s for s in bedrock if s["Action"] == "bedrock:InvokeModel"]

    assert invoke, "missing InvokeModel permission"
    for statement in bedrock:
        assert "*" not in as_list(statement["Action"])
        assert "*" not in as_list(statement["Resource"])
    for statement in invoke:
        resources = json.dumps(statement["Resource"])
        assert "inference-profile/eu.amazon.nova-2-lite-v1:0" in resources
        assert "InferenceProfileArn" in resources  # the application inference profile
        assert "us-" not in resources
        for region in EU_PROFILE_REGIONS:
            assert f"arn:aws:bedrock:{region}::foundation-model/amazon.nova-2-lite-v1:0" in resources


def test_application_inference_profile_copies_the_eu_profile(t):
    t.has_resource_properties(
        "AWS::Bedrock::ApplicationInferenceProfile",
        {
            "InferenceProfileName": "nightmare-nova-2-lite",
            "Description": Match.string_like_regexp(r"^([0-9a-zA-Z:.][ _-]?)+$"),
            "ModelSource": {
                "CopyFrom": Match.string_like_regexp(
                    r"^arn:aws:bedrock:eu-south-2:123456789012:inference-profile/eu\.amazon\.nova-2-lite-v1:0$"
                )
            },
        },
    )
    t.has_output("TextInferenceProfileArn", {})


def test_dynamodb_permissions_are_minimal_per_lambda(t):
    dynamo_actions = sorted(
        tuple(sorted(as_list(s["Action"])))
        for s in statements(t)
        if any(a.startswith("dynamodb:") for a in as_list(s["Action"]))
    )

    assert dynamo_actions == [
        ("dynamodb:DeleteItem", "dynamodb:GetItem", "dynamodb:PutItem"),
        ("dynamodb:PutItem",),
    ]


def test_api_routes_throttling_and_cors(t):
    for route in ("POST /sessions", "POST /sessions/{session_id}/steps"):
        t.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": route})
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "StageName": "$default",
            "AutoDeploy": True,
            "DefaultRouteSettings": {"ThrottlingRateLimit": 5, "ThrottlingBurstLimit": 10},
        },
    )
    t.has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {"CorsConfiguration": Match.object_like({"AllowOrigins": ["http://localhost:4200"]})},
    )
    t.has_output("ApiUrl", {})


def test_allowed_origins_can_be_set_from_context():
    custom = template(allowedOrigins=["https://example.cloudfront.net"])

    custom.has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {"CorsConfiguration": Match.object_like({"AllowOrigins": ["https://example.cloudfront.net"]})},
    )


def test_logs_are_retained_two_weeks(t):
    t.resource_properties_count_is("AWS::Logs::LogGroup", {"RetentionInDays": 14}, 2)
