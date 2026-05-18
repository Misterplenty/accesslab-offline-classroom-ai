# AccessLab Release Readiness Checklist

## A. Validated Now

- [x] AccessLab is packaged as a narrow local-first prototype for document Q&A plus beginner Python bug fixing.
- [x] Strong profile is pinned to `gemma4:e4b`.
- [x] QA default is `baseline`.
- [x] Code tutor default is `hybrid`.
- [x] SQLite-first retrieval is in place, with optional local semantic assist in the same SQLite database.
- [x] OCR fallback exists for scanned/image-based PDFs when optional OCR extras are installed.
- [x] The local code runner is hardened with timeouts, env scrubbing, runtime policy checks, and temp execution directories.
- [x] `/healthz` reports the active model/profile and OCR/semantic state.
- [x] The current repo includes pytest coverage plus dedicated smoke paths for retrieval, OCR, and code-runner hardening.
- [x] The strongest current demo path is clear and reproducible.

## B. Validated Only By Proxy

- [x] Weak profile is pinned to `gemma4:e2b`.
- [x] Weak profile uses baseline QA plus weak-tier discipline behavior.
- [x] Weak-profile behavior is supported by constrained-proxy evidence on a stronger Apple-silicon host.
- [x] Weak-profile benchmark confidence is good enough for prototype packaging, but not for real weak-device deployment claims.

## C. Not Yet Validated

- [ ] Real weak-device latency on actual low-spec hardware
- [ ] Cold-start behavior on slow storage
- [ ] Long-session behavior on real low-spec classroom devices
- [ ] Phone viability
- [ ] SBC viability
- [ ] Any claim that the code runner is a production secure sandbox

## D. Optional But Useful

- [ ] Install `all-minilm` locally to exercise the semantic side of hybrid retrieval
- [ ] Install `requirements-ocr.txt` to demo scanned-PDF OCR fallback
- [ ] Run the heavier benchmark commands if you need to reproduce the current evidence memos locally

## Release Read

AccessLab is ready to present as a validated prototype release candidate and demo/evidence package for its current wedge.

AccessLab is not ready to claim real weak-device deployment proof, phone/SBC readiness, or production sandbox security.
