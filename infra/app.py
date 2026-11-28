#!/usr/bin/env python3
"""CDK entry point for Nightmare Resolver. Base region: eu-west-3 unless NIGHTMARE_REGION is set.

The region does not come from the AWS profile (CDK_DEFAULT_REGION): a profile with another default
region would create a second copy of the stacks there, and the global CloudFront names would clash.

    NightmareResolverWeb  S3 + CloudFront for the Angular app
    NightmareResolver     API (its CORS allows the CloudFront domain and local dev)
"""

import os

import aws_cdk as cdk

from stacks.frontend_stack import FrontendStack
from stacks.nightmare_stack import NightmareStack

LOCAL_DEV_ORIGIN = "http://localhost:4200"

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("NIGHTMARE_REGION", "eu-west-3"),
)

web = FrontendStack(app, "NightmareResolverWeb", env=env)

NightmareStack(
    app,
    "NightmareResolver",
    env=env,
    allowed_origins=[f"https://{web.distribution.distribution_domain_name}", LOCAL_DEV_ORIGIN],
)

cdk.Tags.of(app).add("application", "nightmare")

app.synth()
