# Tech conventions

## Stack
- Frontend: Angular (standalone components, signals), i18n ES/EN, strict TypeScript.
- Backend: Python 3.12 Lambdas, boto3, plain dataclasses (no pydantic: the Lambda zip is just the source folder), pytest.
- Infra: AWS CDK in Python. Base region `eu-south-2`.

## Bedrock models
- Text/reasoning/moderation: `eu.amazon.nova-2-lite-v1:0` (EU inference profile, called from eu-south-2).
  Enable extended thinking only for moderation edge cases and the closing step.
- Images: `stability.stable-image-core-v1:1` in `us-west-2` (fallback: `stability.sd3-5-large-v1:0`).
- Nova Canvas is end-of-life (2026-09-30). Do NOT use it.
- Voice: Amazon Polly (neural voices, es-ES and en-US/en-GB).

## Rules
- All model calls return structured JSON validated in code (Step.from_dict); retry once on invalid output.
- Model ids and regions come from environment variables, never hardcoded in handlers.
- Least-privilege IAM per Lambda. Throttling on API Gateway.
- Keep it simple: plain functions, module-level boto3 clients, no dependency-injection layers.
- Always run tests and `cdk synth` before declaring a task done.
