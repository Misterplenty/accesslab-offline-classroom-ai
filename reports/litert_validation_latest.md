# AccessLab LiteRT-LM Validation

- Generated at: 2026-05-18T10:14:43.056555+00:00
- Backend: litert-lm-validation
- Model target: gemma4:e4b
- Profile: grounded-qa-smoke
- Validation-only: True
- Health: fail - LiteRT-LM validation is configured but no executable probe is set. Set ACCESSLAB_LITERT_LM_COMMAND.
- Command configured: False
- Generation exercised: no
- Total seconds: None

## What This Proves

- The AccessLab runtime boundary can select a non-default LiteRT-LM validation backend.
- A local executable command can be probed through the provider contract when configured.
- Capability reporting stays explicit about generation, streaming, timing, and validation-only limits.

## What This Does Not Prove

- It does not replace Ollama as the default working runtime.
- It does not validate every AccessLab product flow.
- It does not prove support for unsupported phones or low-memory devices.
- It does not move EmbeddingGemma semantic retrieval to an edge embedding runtime.

## Expected Command Contract

- Environment variable: `ACCESSLAB_LITERT_LM_COMMAND`
- The command receives JSON on stdin with model, profile, prompt, context, and settings.
- The command returns plain text or JSON containing `response`, `text`, or `answer`.
- Non-zero exit, empty output, or missing response field is treated as validation failure.

## Future Validation Will Prove

- The target device can execute a local LiteRT-LM generation command for the narrow AccessLab prompt contract.
- The validation backend can return a grounded answer without cloud fallback.
- The measured target can be compared against the Ollama baseline for the same prompt and context.
- The result remains validation-only until broader product flows are run.

## Response

(no response generated)
