# Implementation plan: Nightmare Resolver

- [ ] 1. Project scaffolding
  - [ ] 1.1 Create `backend/` (pyproject, pytest, ruff), `frontend/` (Angular CLI, strict), `infra/` (CDK Python)
  - [ ] 1.2 Add CI workflow: backend tests, frontend build, `cdk synth`
  - _Requirements: 8.1_

- [ ] 2. Shared backend library
  - [ ] 2.1 Pydantic models for Step, Session, Classification, GalleryItem
  - [ ] 2.2 Bedrock Converse wrapper for Nova 2 Lite (JSON output, one retry)
  - [ ] 2.3 Prompt templates ES/EN (story, classifier, sanitizer, anonymizer)
  - _Requirements: 1.4, 3.1, 3.5_

- [ ] 3. Moderation
  - [ ] 3.1 Classifier (`ok | not_serious | forbidden_content | risk`) with tests on a sample corpus
  - [ ] 3.2 Guardrails integration for input/output text
  - [ ] 3.3 Image prompt sanitizer + moderation before image generation
  - _Requirements: 2.1-2.5, 4.1, 4.2_

- [ ] 4. Story engine
  - [ ] 4.1 `start_session` handler (validate, classify, step 1, character bible)
  - [ ] 4.2 `next_step` handler (moderate choice, steps 2-5, closing with learning and coping tip)
  - [ ] 4.3 Session persistence with TTL and no raw text
  - _Requirements: 1.2, 1.3, 3.1-3.5, 7.2, 7.3_

- [ ] 5. Images
  - [ ] 5.1 Stability client in `us-west-2`, S3 storage, fixed style suffix
  - [ ] 5.2 Generate only 2 images (step 1 and rewritten ending), the final one in background, with placeholder fallback
  - _Requirements: 4.1-4.6_

- [ ] 6. Voice
  - [ ] 6.1 `speak` handler with Polly (es-ES / en) and S3 cache
  - _Requirements: 5.1_

- [ ] 7. Gallery
  - [ ] 7.1 Anonymize + re-moderate + publish, delete token
  - [ ] 7.2 Paginated list endpoint
  - _Requirements: 6.1-6.5_

- [ ] 8. Infrastructure (CDK)
  - [ ] 8.1 DataStack: DynamoDB, S3, CloudFront
  - [ ] 8.2 GuardrailStack and ApiStack (Lambdas, API Gateway, throttling, least-privilege IAM)
  - [ ] 8.3 FrontendStack: hosting and deployment
  - _Requirements: 7.1, 8.2_

- [ ] 9. Frontend
  - [ ] 9.1 Home with disclaimer, language switch, input and validation
  - [ ] 9.2 Story view: step, choices, image, loading states
  - [ ] 9.3 Audio player with captions and controls
  - [ ] 9.4 Gallery list/detail and share/delete flow
  - [ ] 9.5 Dark atmospheric theme, reduced-motion, accessibility pass
  - _Requirements: 1.1, 3.2, 5.2, 5.3, 6.5_

- [ ] 10. Hooks and polish
  - [ ] 10.1 Kiro hooks: run backend tests on save, validate prompt templates
  - [ ] 10.2 End-to-end test of the 4 moderation paths and a full story
  - [ ] 10.3 README with architecture and Kiro usage, demo video script
  - _Requirements: 8.1-8.3_
