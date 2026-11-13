"""Root stack. Data, API and frontend resources are added in spec task 8."""

from aws_cdk import CfnOutput, Stack, Tags
from constructs import Construct

from stacks.guardrail import ModerationGuardrail


class NightmareStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        Tags.of(self).add("project", "nightmare-resolver")

        guardrail = ModerationGuardrail(self, "Moderation")

        CfnOutput(self, "BaseRegion", value=self.region)
        CfnOutput(self, "GuardrailId", value=guardrail.guardrail_id)
        CfnOutput(self, "GuardrailVersion", value=guardrail.version)
