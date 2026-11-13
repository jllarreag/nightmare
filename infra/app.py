#!/usr/bin/env python3
"""CDK entry point for Nightmare Resolver. Base region: eu-south-2."""

import os

import aws_cdk as cdk

from stacks.nightmare_stack import NightmareStack

app = cdk.App()

NightmareStack(
    app,
    "NightmareResolver",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "eu-south-2"),
    ),
)

app.synth()
