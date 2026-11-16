import aws_cdk as cdk
from aws_cdk.assertions import Template

from stacks.nightmare_stack import NightmareStack
from stacks.tagging import apply_app_tags


def template(**context) -> Template:
    # Skip Lambda bundling in tests: it needs pip downloads and is checked by `cdk synth`.
    app = cdk.App(context={"aws:cdk:bundling-stacks": [], **context})
    stack = NightmareStack(
        app, "Test", env=cdk.Environment(account="123456789012", region="eu-south-2")
    )
    apply_app_tags(app)  # same as app.py
    return Template.from_stack(stack)
