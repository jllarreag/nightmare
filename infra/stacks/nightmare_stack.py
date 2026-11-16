"""Root stack: moderation guardrail and story API. Images, voice, gallery and frontend come later."""

from aws_cdk import CfnOutput, Stack
from constructs import Construct

from stacks.guardrail import ModerationGuardrail
from stacks.story_api import StoryApi

# Origins allowed to call the API from a browser. The CloudFront domain is added in task 8.
DEFAULT_ALLOWED_ORIGINS = ["http://localhost:4200"]


class NightmareStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        guardrail = ModerationGuardrail(self, "Moderation")
        story = StoryApi(
            self,
            "Story",
            guardrail_arn=guardrail.guardrail_arn,
            guardrail_id=guardrail.guardrail_id,
            guardrail_version=guardrail.version,
            allowed_origins=self.node.try_get_context("allowedOrigins") or DEFAULT_ALLOWED_ORIGINS,
        )

        CfnOutput(self, "BaseRegion", value=self.region)
        CfnOutput(self, "GuardrailId", value=guardrail.guardrail_id)
        CfnOutput(self, "GuardrailVersion", value=guardrail.version)
        CfnOutput(self, "ApiUrl", value=story.api.api_endpoint)
        CfnOutput(self, "TextInferenceProfileArn", value=story.text_profile_arn)
        CfnOutput(self, "SessionsTable", value=story.table.table_name)
