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
    # No se cuentan las Lambdas: auto_delete_objects añade una Lambda propia de CDK.
    for handler, timeout in (("nightmare.handler.handler", 29), ("nightmare.worker.handler", 60)):
        t.has_resource_properties(
            "AWS::Lambda::Function",
            {"Handler": handler, "Runtime": "python3.12", "Timeout": timeout},
        )
    routes = (
        "POST /sessions",
        "POST /sessions/{session_id}/steps",
        "POST /sessions/{session_id}/publish",
        "GET /sessions/{session_id}/images",
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
            "Handler": "nightmare.handler.handler",
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



def _statements(t: Template) -> list[dict]:
    out = []
    for policy in t.find_resources("AWS::IAM::Policy").values():
        stmts = policy["Properties"]["PolicyDocument"]["Statement"]
        role = policy["Properties"]["Roles"][0]["Ref"]
        out += [{**s, "_role": role} for s in stmts]
    return out


def _actions(stmt: dict) -> list[str]:
    a = stmt["Action"]
    return [a] if isinstance(a, str) else a


def test_images_bucket_is_private_with_lifecycle_rules():
    t = synth()
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.object_like({}),
            "LifecycleConfiguration": {
                "Rules": [
                    Match.object_like(
                        {"Prefix": "sessions/", "ExpirationInDays": 1, "Status": "Enabled"}
                    ),
                    Match.object_like(
                        {"Prefix": "gallery/", "ExpirationInDays": 91, "Status": "Enabled"}
                    ),
                ]
            },
        },
    )
    t.has_resource_properties(
        "AWS::S3::BucketPolicy",
        {
            "PolicyDocument": {
                "Statement": Match.array_with(
                    [
                        Match.object_like(
                            {
                                "Effect": "Deny",
                                "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                            }
                        )
                    ]
                )
            }
        },
    )


def test_stability_access_is_only_the_two_us_west_2_models_on_the_worker():
    all_statements = _statements(synth())
    invoke = [s for s in all_statements if _actions(s) == ["bedrock:InvokeModel"]]
    stability = [s for s in invoke if any("us-west-2" in r for r in s["Resource"])]
    assert len(stability) == 1
    assert sorted(stability[0]["Resource"]) == [
        "arn:aws:bedrock:us-west-2::foundation-model/stability.sd3-5-large-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/stability.stable-image-core-v1:1",
    ]
    assert stability[0]["_role"].startswith("ImageWorker")
    # Nova sigue en ambas Lambdas con su ARN eu-*.
    nova = [s for s in invoke if s is not stability[0]]
    assert {s["_role"][:3] for s in nova} == {"Api", "Ima"}
    for s in nova:
        assert "arn:aws:bedrock:eu-*::foundation-model/amazon.nova-2-lite-v1:0" in s["Resource"]


def test_worker_env_vars_and_no_retries():
    t = synth()
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "nightmare.worker.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {
                        "BASE_REGION": "eu-west-3",
                        "TEXT_MODEL_ID": "eu.amazon.nova-2-lite-v1:0",
                        "GUARDRAIL_ID": Match.any_value(),
                        "GUARDRAIL_VERSION": Match.any_value(),
                        "SESSIONS_TABLE": Match.any_value(),
                        "IMAGE_BUCKET": Match.any_value(),
                        "IMAGE_REGION": "us-west-2",
                        "IMAGE_MODEL_ID": "stability.stable-image-core-v1:1",
                        "IMAGE_FALLBACK_MODEL_ID": "stability.sd3-5-large-v1:0",
                    }
                )
            },
        },
    )
    t.has_resource_properties("AWS::Lambda::EventInvokeConfig", {"MaximumRetryAttempts": 0})


def test_api_gets_image_env_and_can_only_invoke_the_worker():
    t = synth()
    t.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "Handler": "nightmare.handler.handler",
            "Environment": {
                "Variables": Match.object_like(
                    {"IMAGE_BUCKET": Match.any_value(), "IMAGE_WORKER_FUNCTION": Match.any_value()}
                )
            },
        },
    )
    invokes = [s for s in _statements(t) if "lambda:InvokeFunction" in _actions(s)]
    assert len(invokes) == 1
    assert invokes[0]["_role"].startswith("ApiServiceRole")
    assert not any(r == "*" for r in invokes[0]["Resource"] if isinstance(r, str))
    assert all("ImageWorker" in str(r) for r in invokes[0]["Resource"])


def test_s3_permissions_are_scoped_to_prefixes():
    t = synth()
    by_role: dict[str, set[str]] = {}
    for s in _statements(t):
        acts = [a for a in _actions(s) if a.startswith("s3:")]
        if not acts or s["_role"].startswith("Custom"):
            continue
        resources = s["Resource"] if isinstance(s["Resource"], list) else [s["Resource"]]
        for a in acts:
            for r in resources:
                text = str(r)
                assert "sessions/*" in text or "gallery/*" in text, (a, text)
                by_role.setdefault(s["_role"][:3], set()).add(a)
    assert by_role["Ima"] == {"s3:PutObject"}
    assert by_role["Api"] == {"s3:GetObject", "s3:PutObject", "s3:DeleteObject"}