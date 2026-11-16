#!/usr/bin/env python3
"""CDK entry point for Nightmare Resolver. Base region: eu-south-2 unless CDK_DEFAULT_REGION is set."""

import os

import aws_cdk as cdk

from stacks.nightmare_stack import NightmareStack
from stacks.tagging import apply_app_tags

app = cdk.App()

NightmareStack(
    app,
    "NightmareResolver",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-south-2"),
    ),
)

# At app level, so the stack and every resource (including future stacks) get the tags.
apply_app_tags(app)

app.synth()
