# Safety and moderation rules

These rules are mandatory for every feature touching user text, model output or published content.

## Classification of each user input
Classify with Nova (`ok`, `not_serious`, `forbidden_content`, `risk`):
- `ok`: valid fear, even if dark. Nightmares are often violent; emotional, genuine content is valid.
- `not_serious`: trolling, nonsense, gratuitous requests. End the session politely, store nothing.
- `forbidden_content`: gratuitous gore or sexual content. End the session neutrally, store nothing.
- `risk`: self-harm, suicidal ideation, abuse or severe trauma. Stop generation, show a supportive
  message and help resources (Spain 024 / 112, international: findahelpline.com). Never cut off coldly.

## Layers
1. Bedrock Guardrails on input and output text.
2. LLM classifier on every user input.
3. Moderation of the generated image prompt BEFORE sending it to the image model
   (the image models do not support Guardrails).
4. Moderation of the final story before it can be published.

## Privacy
- The raw nightmare text never leaves the EU region. Only a sanitized, generic visual prompt (no
  names, places, identifiable data) is sent to `us-west-2` for image generation.
- Nothing is public by default. Publishing is opt-in, anonymized, and deletable with a private token.
- Do not log raw user text. Log only ids, categories and metrics.

## Tone
Warm, calm, never clinical or alarming. Never blame the user. Never promise a cure.
Always show the disclaimer: self-help tool, not a medical treatment.
