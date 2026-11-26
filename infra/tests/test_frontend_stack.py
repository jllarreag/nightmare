import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from stacks.frontend_stack import FrontendStack
from stacks.nightmare_stack import NightmareStack

ENV = cdk.Environment(account="123456789012", region="eu-west-3")


def test_bucket_is_private_and_served_through_cloudfront_oac():
    t = Template.from_stack(FrontendStack(cdk.App(), "Web", env=ENV))
    t.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )
    t.resource_count_is("AWS::CloudFront::OriginAccessControl", 1)
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultRootObject": "index.html",
                    "DefaultCacheBehavior": Match.object_like(
                        {"ViewerProtocolPolicy": "redirect-to-https"}
                    ),
                }
            )
        },
    )


def test_api_cors_allows_the_cloudfront_domain():
    app = cdk.App()
    web = FrontendStack(app, "Web", env=ENV)
    api = NightmareStack(
        app,
        "Api",
        env=ENV,
        allowed_origins=[f"https://{web.distribution.distribution_domain_name}"],
    )
    cors = Template.from_stack(api).find_resources("AWS::ApiGatewayV2::Api")
    origins = next(iter(cors.values()))["Properties"]["CorsConfiguration"]["AllowOrigins"]
    assert len(origins) == 1 and "Fn::" in str(origins[0])  # referencia al otro stack
