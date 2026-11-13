"""Root stack. Resources (data, guardrails, API, frontend) are added in spec task 8."""

from aws_cdk import CfnOutput, Stack, Tags
from constructs import Construct


class NightmareStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        Tags.of(self).add("project", "nightmare-resolver")

        CfnOutput(self, "BaseRegion", value=self.region)
