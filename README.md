# Nightmare Resolver

> Tell us your nightmare. Rewrite its ending.

Nightmare Resolver turns a nightmare into an illustrated, interactive story that guides the user through
**Imagery Rehearsal Therapy (IRT)**-inspired steps: confront, take control, rewrite the ending, and
close with a learning. Built for Kiroween 2026 with Kiro.

Nightmare Resolver is a self-help companion, **not** a medical treatment or a substitute for professional care.

## Stack

| Layer | Technology |
|---|---|
| Frontend | Angular (ES / EN) |
| Backend | AWS Lambda (Python) + API Gateway |
| Story, moderation | Amazon Nova 2 Lite on Bedrock (`eu.amazon.nova-2-lite-v1:0`) |
| Images | Stability AI on Bedrock (`us-west-2`, only sanitized visual prompts leave the EU) |
| Voice | Amazon Polly |
| Data | DynamoDB, S3, CloudFront |
| Infra | AWS CDK (Python), base region `eu-south-2` |

## Repository layout

```
.kiro/        steering, specs and hooks (Kiro)
backend/      Python Lambdas
frontend/     Angular app
infra/        AWS CDK app
```

## Status

Work in progress. See `.kiro/specs/lucid/` for requirements, design and tasks.

## License

MIT
