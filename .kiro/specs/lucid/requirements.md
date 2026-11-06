# Requirements: Nightmare Resolver

## Introduction
Nightmare Resolver converts a user's nightmare into an illustrated, interactive 5-step story inspired by Imagery
Rehearsal Therapy, with optional voice narration, ending in a learning. Anonymous use, ES/EN,
with an opt-in public gallery of anonymized stories.

## Requirement 1: Submit a nightmare
**User story:** As a user, I want to describe my nightmare so that the app builds a story from it.

Acceptance criteria:
1. WHEN the user opens the app THEN the system SHALL show a disclaimer that Nightmare Resolver is a self-help tool and not a medical treatment.
2. WHEN the user submits a nightmare text (min 20, max 2000 chars) THEN the system SHALL classify it before generating anything.
3. WHEN the input is outside the length limits THEN the system SHALL show a validation message and not call any model.
4. The system SHALL let the user choose ES or EN, and the story SHALL be generated in that language.

## Requirement 2: Safety and moderation
**User story:** As an operator, I want unsafe or non-serious input blocked so the app stays safe and useful.

Acceptance criteria:
1. WHEN input is classified `not_serious` or `forbidden_content` THEN the system SHALL end the session with a neutral message and SHALL NOT store any content.
2. WHEN input is classified `risk` THEN the system SHALL stop generation, show supportive text and help resources, and SHALL NOT store content.
3. WHEN input is a genuine, dark but emotional nightmare THEN the system SHALL accept it (`ok`).
4. WHILE generating, the system SHALL moderate every user choice, every generated step and every image prompt.
5. WHEN a moderation check fails mid-story THEN the system SHALL stop and end the session safely.

## Requirement 3: Interactive story
**User story:** As a user, I want a guided story with choices so I can confront my fear step by step.

Acceptance criteria:
1. The system SHALL generate a story of exactly 5 steps: recreate, take control, decision, rewrite, closing.
2. WHEN a step is shown THEN the system SHALL present 2 or 3 choices (except the closing step).
3. WHEN the user picks a choice THEN the system SHALL generate the next step consistent with the earlier ones.
4. The closing step SHALL include a learning and one practical coping tip.
5. Each step SHALL include a narrative text of at most 120 words.

## Requirement 4: Images
**User story:** As a user, I want an image per step so the story feels vivid.

Acceptance criteria:
1. The system SHALL generate exactly two images per story: one for step 1 (the nightmare) and one for step 4 (the rewritten, healing ending), using sanitized visual prompts with no personal data.
2. The raw nightmare text SHALL NOT be sent outside the EU region.
3. The system SHALL apply the fixed visual style and a consistent main character across both images.
4. WHILE the user reads step 1 THEN the system SHOULD generate the final image in the background.
5. WHEN image generation fails THEN the system SHALL show a placeholder and continue the story.
6. Steps without an image SHALL use the nearest generated image or a neutral atmospheric background.

## Requirement 5: Voice narration
**User story:** As a user, I want the story read aloud.

Acceptance criteria:
1. WHEN the user presses play THEN the system SHALL read the step text with a voice matching the language.
2. The system SHALL show the text as captions while playing.
3. The user SHALL be able to pause, resume and mute.

## Requirement 6: Public gallery (opt-in)
**User story:** As a user, I want to optionally share my finished story anonymously.

Acceptance criteria:
1. Nothing SHALL be published by default.
2. WHEN a story finishes THEN the system SHALL offer a "share" action.
3. WHEN the user shares THEN the system SHALL anonymize the story (remove names, places, identifying details), re-moderate it, and only then publish.
4. The system SHALL give the user a private token to delete the published story.
5. The gallery SHALL list published stories with their images, paginated, in ES/EN.

## Requirement 7: Abuse and cost control
Acceptance criteria:
1. The system SHALL rate limit requests per IP and cap the number of sessions per day.
2. The system SHALL NOT log raw user text.
3. Sessions SHALL expire automatically (TTL) if not shared.

## Requirement 8: Hackathon deliverables
Acceptance criteria:
1. The repository SHALL be public with an MIT license and a visible `/.kiro` folder (specs, steering, hooks).
2. The app SHALL be deployed and reachable via public URL.
3. The README SHALL explain setup, architecture and Kiro usage.
