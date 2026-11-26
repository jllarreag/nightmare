import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.nightmare_stack import NightmareStack


def synth(**context) -> Template:
    app = cdk.App(context=context)
    stack = NightmareStack(
        app, "Test", env=cdk.Environment(account="123456789012", region="eu-west-3")
    )
    return Template.from_stack(stack)


def test_one_lambda_api_routes_and_sessions_table():
    t = synth()
    t.resource_count_is("AWS::Lambda::Function", 1)
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {"Handler": "nightmare.handler.handler", "Runtime": "python3.12", "Timeout": 29},
    )
    routes = (
        "POST /sessions",
        "POST /sessions/{session_id}/steps",
        "POST /sessions/{session_id}/publish",
        "GET /gallery",
        "DELETE /gallery/{story_id}",
    )
    for route in routes:
        t.has_resource_properties("AWS::ApiGatewayV2::Route", {"RouteKey": route})
    t.has_resource_properties(
        "AWS::DynamoDB::Table",
        {"TimeToLiveSpecification": {"AttributeName": "ttl", "Enabled": True}},
    )


def test_bedrock_permissions_are_not_wildcards_on_everything():
    t = synth()
    t.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Action": "bedrock:InvokeModel",
                                "Resource": Match.array_with(
                                    ["arn:aws:bedrock:eu-*::foundation-model/amazon.nova-2-lite-v1:0"]
                                ),
                            }
                        )
                    ]
                )
            }
        },
    )


def test_guardrail_has_self_harm_topic():
    synth().has_resource_properties(
        "AWS::Bedrock::Guardrail",
        {"TopicPolicyConfig": {"TopicsConfig": Match.array_with([Match.object_like({"Name": "SelfHarm"})])}},
    )


def test_allowed_origins_from_context():
    synth(allowedOrigins=["https://example.cloudfront.net"]).has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {"CorsConfiguration": Match.object_like({"AllowOrigins": ["https://example.cloudfront.net"]})},
    )


def test_gallery_index_does_not_project_the_token_hash():
    t = synth()
    t.has_resource_properties(
        "AWS::DynamoDB::Table",
        {
            "GlobalSecondaryIndexes": [
                Match.object_like(
                    {
                        "IndexName": "gallery",
                        "KeySchema": [
                            {"AttributeName": "gpk", "KeyType": "HASH"},
                            {"AttributeName": "gsk", "KeyType": "RANGE"},
                        ],
                        "Projection": {
                            "ProjectionType": "INCLUDE",
                            "NonKeyAttributes": ["id", "language", "created_at", "story", "ttl"],
                        },
                    }
                )
            ]
        },
    )


def test_gallery_settings_reach_the_lambda():
    synth().has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Environment": {
                "Variables": Match.object_like(
                    {"GALLERY_TTL_DAYS": "90", "GALLERY_INDEX": "gallery"}
                )
            }
        },
    )


def test_cors_allows_delete_and_the_token_header():
    synth().has_resource_properties(
        "AWS::ApiGatewayV2::Api",
        {
            "CorsConfiguration": Match.object_like(
                {
                    "AllowMethods": Match.array_with(["GET", "POST", "DELETE"]),
                    "AllowHeaders": Match.array_with(["content-type", "x-delete-token"]),
                }
            )
        },
    )
