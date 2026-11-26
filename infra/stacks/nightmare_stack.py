"""Stack único: guardrail, tabla de sesiones, una Lambda y una HTTP API.

    POST /sessions                      -> empieza una sesión (pesadilla -> paso 1)
    POST /sessions/{session_id}/steps   -> avanza (elección -> siguiente paso)
"""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

from stacks.guardrail import ModerationGuardrail

BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"

# Perfil de inferencia UE de Nova 2 Lite: las peticiones no salen de regiones europeas.
NOVA_PROFILE = "eu.amazon.nova-2-lite-v1:0"
NOVA_MODEL = "amazon.nova-2-lite-v1:0"

# Orígenes que pueden llamar a la API desde el navegador. app.py pasa el dominio de CloudFront;
# `cdk deploy -c allowedOrigins=...` tiene prioridad.
DEFAULT_ALLOWED_ORIGINS = ["http://localhost:4200"]


class NightmareStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        allowed_origins: list[str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        guardrail = ModerationGuardrail(self, "Moderation")

        # Sesiones: expiran a las 24 h (el backend rellena `ttl`).
        table = dynamodb.Table(
            self,
            "Sessions",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,  # hackatón: `cdk destroy` lo borra todo
        )

        # El código es solo Python + boto3 (ya incluido en Lambda): se sube la carpeta tal cual.
        function = lambda_.Function(
            self,
            "Api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=lambda_.Code.from_asset(
                str(BACKEND_SRC), exclude=["**/__pycache__", "**/*.egg-info"]
            ),
            handler="nightmare.handler.handler",
            memory_size=512,
            timeout=Duration.seconds(29),  # la HTTP API corta a los 30 s
            environment={
                "BASE_REGION": self.region,
                "TEXT_MODEL_ID": NOVA_PROFILE,
                "GUARDRAIL_ID": guardrail.guardrail_id,
                "GUARDRAIL_VERSION": guardrail.version,
                "SESSIONS_TABLE": table.table_name,
            },
        )
        table.grant_read_write_data(function)
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    # Bedrock comprueba el perfil UE y el modelo en cada región del perfil.
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{NOVA_PROFILE}",
                    f"arn:aws:bedrock:eu-*::foundation-model/{NOVA_MODEL}",
                ],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"], resources=[guardrail.guardrail_arn]
            )
        )

        api = apigw.HttpApi(
            self,
            "HttpApi",
            api_name="nightmare-resolver",
            create_default_stage=False,
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=self.node.try_get_context("allowedOrigins")
                or allowed_origins
                or DEFAULT_ALLOWED_ORIGINS,
                allow_methods=[apigw.CorsHttpMethod.POST],
                allow_headers=["content-type"],
            ),
        )
        apigw.HttpStage(
            self,
            "DefaultStage",
            http_api=api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=5, burst_limit=10),  # tope global de coste
        )
        integration = integrations.HttpLambdaIntegration("Lambda", function)
        for path in ("/sessions", "/sessions/{session_id}/steps"):
            api.add_routes(path=path, methods=[apigw.HttpMethod.POST], integration=integration)

        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
