import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.nightmare_stack import NightmareStack


def template(**context) -> Template:
    # Skip Lambda bundling in tests: it needs pip downloads and is checked by `cdk synth`.
    app = cdk.App(context={"aws:cdk:bundling-stacks": [], **context})
    stack = NightmareStack(
        app, "Test", env=cdk.Environment(account="123456789012", region="eu-south-2")
    )
    return Template.from_stack(stack)
