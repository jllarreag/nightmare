"""Story API: DynamoDB sessions table, two Lambdas and an HTTP API.

    POST /sessions                      -> StartSession  (nightmare -> step 1)
    POST /sessions/{session_id}/steps   -> NextStep      (choice -> next step)
"""

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

from stacks.bundling import backend_code

TEXT_INFERENCE_PROFILE = "eu.amazon.nova-2-lite-v1:0"
TEXT_FOUNDATION_MODEL = "amazon.nova-2-lite-v1:0"
# Destination regions of the EU inference profile: requests never leave these regions.
EU_PROFILE_REGIONS = [
    "eu-central-1",
    "eu-north-1",
    "eu-south-1",
    "eu-south-2",
    "eu-west-1",
    "eu-west-3",
]

# Global limits for the whole API, to cap cost. Per-IP limits come later with WAF.
RATE_LIMIT_PER_SECOND = 5
BURST_LIMIT = 10


class StoryApi(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        guardrail_arn: str,
        guardrail_id: str,
        guardrail_version: str,
        allowed_origins: list[str],
    ) -> None:
        super().__init__(scope, construct_id)
        stack = Stack.of(self)

        # --- Data -------------------------------------------------------------------------
        self.table = dynamodb.Table(
            self,
            "Sessions",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # Sessions expire after 24 h (set by the backend); DynamoDB then deletes them.
            time_to_live_attribute="ttl",
            # Hackathon project: `cdk destroy` removes the table and its temporary sessions.
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- Tagged access to Nova ---------------------------------------------------------
        # On-demand model calls cannot be tagged. Calling Nova through this application
        # inference profile attaches its tags to the Bedrock billing records.
        system_profile_arn = (
            f"arn:aws:bedrock:{stack.region}:{stack.account}:"
            f"inference-profile/{TEXT_INFERENCE_PROFILE}"
        )
        text_profile = bedrock.CfnApplicationInferenceProfile(
            self,
            "TextInferenceProfile",
            inference_profile_name="nightmare-nova-2-lite",
            # Pattern ^([0-9a-zA-Z:.][ _-]?)+$ : no commas or parentheses.
            description="Nova 2 Lite EU for Nightmare Resolver cost allocation",
            model_source=bedrock.CfnApplicationInferenceProfile.InferenceProfileModelSourceProperty(
                copy_from=system_profile_arn
            ),
        )
        self.text_profile_arn = text_profile.attr_inference_profile_arn

        # --- Lambdas ----------------------------------------------------------------------
        code = backend_code()
        environment = {
            "BASE_REGION": stack.region,
            "TEXT_MODEL_ID": self.text_profile_arn,
            "GUARDRAIL_ID": guardrail_id,
            "GUARDRAIL_VERSION": guardrail_version,
            "SESSIONS_TABLE": self.table.table_name,
        }

        def function(name: str, handler: str) -> lambda_.Function:
            return lambda_.Function(
                self,
                name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                architecture=lambda_.Architecture.ARM_64,
                code=code,
                handler=handler,
                memory_size=512,
                # The HTTP API gives up after 30 s.
                timeout=Duration.seconds(29),
                environment=environment,
                logging_format=lambda_.LoggingFormat.JSON,
                application_log_level_v2=lambda_.ApplicationLogLevel.INFO,
                log_group=logs.LogGroup(
                    self,
                    f"{name}Logs",
                    retention=logs.RetentionDays.TWO_WEEKS,
                    removal_policy=RemovalPolicy.DESTROY,
                ),
            )

        self.start_session = function("StartSession", "nightmare.handlers.start_session.handler")
        self.next_step = function("NextStep", "nightmare.handlers.next_step.handler")

        # --- Least-privilege permissions --------------------------------------------------
        # Bedrock checks the whole chain: application profile -> EU profile -> model per region.
        invoke_nova = iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                self.text_profile_arn,
                system_profile_arn,
                *(
                    f"arn:aws:bedrock:{region}::foundation-model/{TEXT_FOUNDATION_MODEL}"
                    for region in EU_PROFILE_REGIONS
                ),
            ],
        )
        apply_guardrail = iam.PolicyStatement(
            actions=["bedrock:ApplyGuardrail"], resources=[guardrail_arn]
        )
        for fn in (self.start_session, self.next_step):
            fn.add_to_role_policy(invoke_nova)
            fn.add_to_role_policy(apply_guardrail)

        self.table.grant(self.start_session, "dynamodb:PutItem")
        self.table.grant(
            self.next_step, "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:DeleteItem"
        )

        # --- HTTP API ---------------------------------------------------------------------
        self.api = apigw.HttpApi(
            self,
            "Api",
            api_name="nightmare-resolver",
            create_default_stage=False,
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=allowed_origins,
                allow_methods=[apigw.CorsHttpMethod.POST],
                allow_headers=["content-type"],
                max_age=Duration.hours(1),
            ),
        )
        self.stage = apigw.HttpStage(
            self,
            "DefaultStage",
            http_api=self.api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(
                rate_limit=RATE_LIMIT_PER_SECOND, burst_limit=BURST_LIMIT
            ),
        )
        self.api.add_routes(
            path="/sessions",
            methods=[apigw.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("StartSession", self.start_session),
        )
        self.api.add_routes(
            path="/sessions/{session_id}/steps",
            methods=[apigw.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("NextStep", self.next_step),
        )
