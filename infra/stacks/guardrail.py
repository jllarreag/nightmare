"""Bedrock Guardrail used through ApplyGuardrail by the moderation layer.

Calibrated for nightmares: violent dreams are common and valid, so input VIOLENCE is LOW and the
Nova classifier decides what is gratuitous. The SelfHarm denied topic is mapped to `risk` by
backend/src/nightmare/safety.py (SELF_HARM_TOPIC) and must keep that exact name.
"""

from aws_cdk import aws_bedrock as bedrock
from constructs import Construct

SELF_HARM_TOPIC = "SelfHarm"

# (type, input strength, output strength)
_FILTERS = [
    ("SEXUAL", "HIGH", "HIGH"),
    ("VIOLENCE", "LOW", "MEDIUM"),
    ("HATE", "HIGH", "HIGH"),
    ("INSULTS", "MEDIUM", "HIGH"),
    ("MISCONDUCT", "MEDIUM", "HIGH"),
    # Prompt attacks only apply to input; output strength must be NONE.
    ("PROMPT_ATTACK", "HIGH", "NONE"),
]


class ModerationGuardrail(Construct):
    def __init__(self, scope: Construct, construct_id: str) -> None:
        super().__init__(scope, construct_id)

        # The app maps interventions to its own localized messages; these are a fallback only.
        blocked = "This content can't be processed. / Este contenido no se puede procesar."

        guardrail = bedrock.CfnGuardrail(
            self,
            "Guardrail",
            name="nightmare-resolver-moderation",
            description="Input/output moderation for Nightmare Resolver stories",
            blocked_input_messaging=blocked,
            blocked_outputs_messaging=blocked,
            content_policy_config=bedrock.CfnGuardrail.ContentPolicyConfigProperty(
                filters_config=[
                    bedrock.CfnGuardrail.ContentFilterConfigProperty(
                        type=kind, input_strength=input_strength, output_strength=output_strength
                    )
                    for kind, input_strength, output_strength in _FILTERS
                ]
            ),
            topic_policy_config=bedrock.CfnGuardrail.TopicPolicyConfigProperty(
                topics_config=[
                    bedrock.CfnGuardrail.TopicConfigProperty(
                        name=SELF_HARM_TOPIC,
                        type="DENY",
                        definition=(
                            "The person expresses a real wish or plan to hurt or kill themselves, "
                            "or describes current self-harm, outside of a dream narrative."
                        ),
                        examples=[
                            "I want to end my life",
                            "Pienso en suicidarme",
                            "I have been cutting myself again",
                            "Sería mejor no despertar nunca más",
                        ],
                    )
                ]
            ),
        )

        version = bedrock.CfnGuardrailVersion(
            self,
            "Version",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description="Initial moderation policy",
        )

        self.guardrail_id = guardrail.attr_guardrail_id
        self.guardrail_arn = guardrail.attr_guardrail_arn
        self.version = version.attr_version
