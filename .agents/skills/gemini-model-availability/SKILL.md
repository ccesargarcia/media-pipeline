---
name: gemini-model-availability
description: >-
  Directs model selection for Google Gemini API tasks. Enforces that Gemini 2.5
  is strictly NOT available and must never be referenced, invoked, or suggested.
---

# Google Gemini Model Availability & Constraints

## CRITICAL RULE: Gemini 2.5 is NOT available
- **NEVER** suggest, configure, or attempt to use `gemini-2.5`, `gemini-2.5-flash`, or any `2.5` variant.
- The user has explicitly confirmed that **Gemini 2.5 does NOT exist or is NOT available** in their Google AI Studio account/environment.

## Permitted Models
When interacting with Google Gemini API:
- For fast / high-throughput tasks (e.g. translation, subtitles): use **`gemini-1.5-flash`** or **`gemini-2.0-flash`**.
- For high-reasoning tasks: use **`gemini-1.5-pro`**.
- Default fallback model for API scripts: `gemini-1.5-flash`.
