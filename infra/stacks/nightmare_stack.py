"""Stack único: guardrail, tabla de sesiones, dos Lambdas, un bucket de imágenes y una HTTP API.

    POST /sessions                      -> empieza una sesión (pesadilla -> paso 1)
    POST /sessions/{session_id}/steps   -> avanza (elección -> siguiente paso)
    POST /sessions/{session_id}/publish -> publica la historia terminada (opt-in)
    GET /sessions/{session_id}/images   -> estado y URL firmada de las imágenes (sondeo)
    GET /gallery                        -> galería pública paginada
    DELETE /gallery/{story_id}          -> borra una historia (cabecera x-delete-token)

La Lambda de la API lanza de forma asíncrona la Lambda ImageWorker, que es la única con acceso
a Stability (us-west-2) y la única que escribe imágenes de sesión en el bucket privado.
"""
from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

from stacks.guardrail import ModerationGuardrail

BACKEND_SRC = Path(__file__).resolve().parents[2] / "backend" / "src"

# Perfil de inferencia UE de Nova 2 Lite: las peticiones no salen de regiones europeas.
NOVA_PROFILE = "eu.amazon.nova-2-lite-v1:0"
NOVA_MODEL = "amazon.nova-2-lite-v1:0"

# Orígenes que pueden llamar a la API desde el navegador. app.py pasa el dominio de CloudFront;
# `cdk deploy -c allowedOrigins=...` tiene prioridad.
DEFAULT_ALLOWED_ORIGINS = ["http://localhost:4200"]
# Días que vive una historia publicada en la galería (0 = sin caducidad).
GALLERY_TTL_DAYS = 90

# Imágenes: Stability solo está en us-west-2; el worker recibe acceso a estos dos modelos y a nada más.
IMAGE_REGION = "us-west-2"
IMAGE_MODEL = "stability.stable-image-core-v1:1"
IMAGE_FALLBACK_MODEL = "stability.sd3-5-large-v1:0"


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

        # Índice de la galería: las historias publicadas (pk STORY#<id>) se listan por idioma,
        # las más nuevas primero. No proyecta token_hash: listar nunca puede devolver el hash.
        table.add_global_secondary_index(
            index_name="gallery",
            partition_key=dynamodb.Attribute(name="gpk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="gsk", type=dynamodb.AttributeType.STRING),
            projection_type=dynamodb.ProjectionType.INCLUDE,
            non_key_attributes=["id", "language", "created_at", "story", "ttl"],
        )

        # Imágenes privadas: sessions/ vive 1 día (como la sesión) y gallery/ lo que la historia publicada.
        lifecycle_rules = [
            s3.LifecycleRule(id="SessionImages", prefix="sessions/", expiration=Duration.days(1))
        ]
        if GALLERY_TTL_DAYS > 0:
            lifecycle_rules.append(
                s3.LifecycleRule(
                    id="GalleryImages",
                    prefix="gallery/",
                    expiration=Duration.days(GALLERY_TTL_DAYS + 1),
                )
            )
        bucket = s3.Bucket(
            self,
            "Images",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,  # hackatón: `cdk destroy` lo borra todo
            auto_delete_objects=True,
            lifecycle_rules=lifecycle_rules,
        )

        # Permiso de Nova compartido por la API y el worker.
        nova_statement = iam.PolicyStatement(
            actions=["bedrock:InvokeModel"],
            resources=[
                # Bedrock comprueba el perfil UE y el modelo en cada región del perfil.
                f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{NOVA_PROFILE}",
                f"arn:aws:bedrock:eu-*::foundation-model/{NOVA_MODEL}",
            ],
        )
        asset = lambda_.Code.from_asset(
            str(BACKEND_SRC), exclude=["**/__pycache__", "**/*.egg-info"]
        )

        # Worker de imágenes: sin reintentos (captura todo y guarda `failed`; reintentar solo
        # duplicaría llamadas de pago). Mismo código que la API, otro handler.
        worker = lambda_.Function(
            self,
            "ImageWorker",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=asset,
            handler="nightmare.worker.handler",
            memory_size=512,
            timeout=Duration.seconds(60),
            retry_attempts=0,
            environment={
                "BASE_REGION": self.region,
                "TEXT_MODEL_ID": NOVA_PROFILE,
                "GUARDRAIL_ID": guardrail.guardrail_id,
                "GUARDRAIL_VERSION": guardrail.version,
                "SESSIONS_TABLE": table.table_name,
                "IMAGE_BUCKET": bucket.bucket_name,
                "IMAGE_REGION": IMAGE_REGION,
                "IMAGE_MODEL_ID": IMAGE_MODEL,
                "IMAGE_FALLBACK_MODEL_ID": IMAGE_FALLBACK_MODEL,
            },
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:GetItem", "dynamodb:PutItem"], resources=[table.table_arn]
            )
        )
        worker.add_to_role_policy(nova_statement)
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"], resources=[guardrail.guardrail_arn]
            )
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{IMAGE_REGION}::foundation-model/{IMAGE_MODEL}",
                    f"arn:aws:bedrock:{IMAGE_REGION}::foundation-model/{IMAGE_FALLBACK_MODEL}",
                ],
            )
        )
        worker.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"], resources=[bucket.arn_for_objects("sessions/*")]
            )
        )

        # El código es solo Python + boto3 (ya incluido en Lambda): se sube la carpeta tal cual.
        function = lambda_.Function(
            self,
            "Api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            code=asset,
            handler="nightmare.handler.handler",
            memory_size=512,
            timeout=Duration.seconds(29),  # la HTTP API corta a los 30 s
            environment={
                "BASE_REGION": self.region,
                "TEXT_MODEL_ID": NOVA_PROFILE,
                "GUARDRAIL_ID": guardrail.guardrail_id,
                "GUARDRAIL_VERSION": guardrail.version,
                "SESSIONS_TABLE": table.table_name,
                "GALLERY_INDEX": "gallery",
                "GALLERY_TTL_DAYS": str(GALLERY_TTL_DAYS),
                "IMAGE_BUCKET": bucket.bucket_name,
                "IMAGE_WORKER_FUNCTION": worker.function_name,
            },
        )
        table.grant_read_write_data(function)
        function.add_to_role_policy(nova_statement)
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:ApplyGuardrail"], resources=[guardrail.guardrail_arn]
            )
        )
        worker.grant_invoke(function)
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[bucket.arn_for_objects("sessions/*"), bucket.arn_for_objects("gallery/*")],
            )
        )
        function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject", "s3:DeleteObject"],
                resources=[bucket.arn_for_objects("gallery/*")],
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
                allow_methods=[
                    apigw.CorsHttpMethod.GET,
                    apigw.CorsHttpMethod.POST,
                    apigw.CorsHttpMethod.DELETE,
                ],
                allow_headers=["content-type", "x-delete-token"],
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
        routes = [
            ("/sessions", apigw.HttpMethod.POST),
            ("/sessions/{session_id}/steps", apigw.HttpMethod.POST),
            ("/sessions/{session_id}/publish", apigw.HttpMethod.POST),
            ("/sessions/{session_id}/images", apigw.HttpMethod.GET),
            ("/gallery", apigw.HttpMethod.GET),
            ("/gallery/{story_id}", apigw.HttpMethod.DELETE),
        ]
        for path, method in routes:
            api.add_routes(path=path, methods=[method], integration=integration)

        CfnOutput(self, "ApiUrl", value=api.api_endpoint)
