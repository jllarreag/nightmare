import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.nightmare_stack import NightmareStack


def synth(**context) -> Template:
    app = cdk.App(context=context)
    stack = NightmareStack(
        app, "Test", env=cdk.Environment(account="123456789012", region="eu-south-2")
    )
    return Template.from_stack(stack)


def test_one_lambda_two_routes_and_sessions_table():
    t = synth()
    t.resource_count_is("AWS::Lambda::Function", 1)
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {"Handler": "nightmare.handler.handler", "Runtime": "python3.12", "Timeout": 29},
    )
    for route in ("POST /sessions", "POST /sessions/{session_id}/steps"):
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
