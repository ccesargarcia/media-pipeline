---
name: gemini-model-availability
description: >-
  Enforces Google Gemini model selection rules: Gemini operates from version 3.x onwards
  (e.g., gemini-3.0-flash, gemini-3-flash-preview). Version 2.5 is strictly NOT available.
---

# Google Gemini Model Availability & Constraints

## CRITICAL RULES:
1. **Gemini 2.5 is strictly NOT available**: NEVER reference, suggest, or invoke `gemini-2.5` or any 2.5 variant.
2. **Gemini operates from version 3.x onwards**:
   - Primary models: **`gemini-3.0-flash`**, **`gemini-3-flash-preview`**, **`gemini-3-flash`**, or **`gemini-flash-latest`**.
   - For high reasoning: **`gemini-3.0-pro`** (or 3.x equivalents).
   - Only select models within the 3.x series or dynamic aliases resolving to 3.x.
