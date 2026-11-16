"""Cost allocation tags shared by every resource of the app.

To see costs per app in Cost Explorer, these keys must also be activated as cost allocation tags
in Billing of the management account (see docs/documento-tecnico.md, section 7).
"""

import aws_cdk as cdk
from constructs import IConstruct

APP_TAGS = {"application": "nightmare"}


def apply_app_tags(scope: IConstruct) -> None:
    """Tag the scope and everything below it, including the CloudFormation stack itself."""
    for key, value in APP_TAGS.items():
        cdk.Tags.of(scope).add(key, value)
