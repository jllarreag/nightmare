"""Web estática: bucket S3 privado servido solo a través de CloudFront (Origin Access Control).

El contenido se sube con `scripts/deploy-frontend.bat` (o `.sh`), no con CDK.
"""

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from constructs import Construct


class FrontendStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,  # hackatón: `cdk destroy` lo borra todo
            auto_delete_objects=True,
        )

        self.distribution = cloudfront.Distribution(
            self,
            "Cdn",
            comment="nightmare-resolver web",
            default_root_object="index.html",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                # Respeta el Cache-Control que pone el script de subida (no-cache en index/config).
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                compress=True,
            ),
            # SPA: cualquier ruta desconocida devuelve index.html.
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=status,
                    response_http_status=200,
                    response_page_path="/index.html",
                    ttl=Duration.seconds(0),
                )
                for status in (403, 404)
            ],
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # Europa y Norteamérica
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
        )

        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        CfnOutput(self, "SiteUrl", value=f"https://{self.distribution.distribution_domain_name}")
