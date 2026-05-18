PYTHON ?= $(shell if [ -x .venv/bin/python ]; then printf .venv/bin/python; else printf python3; fi)
JUDGE_PYTHON ?= .venv/bin/python
DEVICE_LABEL ?= local-benchmark
DEVICE_TIER ?= decent
MODEL ?=
RUNTIME_BACKEND ?=
DEPLOYMENT_MODE ?=
RETRIEVAL_MODE ?=
NUM_THREAD ?=
NUM_GPU ?=
NUM_CTX ?=
SUMMARIES ?=
RUN_LABEL ?=
COLD_WARM ?= warm
PROMPT_VARIANT ?=
QA_PROMPT_VARIANT ?=
CODE_PROMPT_VARIANT ?=
QA_DISCIPLINE_PROFILE ?=
CATEGORIES ?=
DOCUMENT ?=
PDF ?=
QUESTION ?=
EXPECTED_SUBSTRING ?=
EXPORT_OUTPUT ?=
SOURCE_TYPE ?=
SESSION_ID ?=
QUALITY_LABEL ?=
LABEL_NOTE ?=
PRESET ?=
LOAD_JOBS ?= 12
LOAD_MAX_CONCURRENT_JOBS ?= 1
HEALTHZ_URL ?= http://127.0.0.1:8000/healthz
JUDGE_HOST ?= 127.0.0.1
JUDGE_PORT ?= 8000
JUDGE_DATA_DIR ?= $(CURDIR)/data/judge-demo
JUDGE_CLASS_SPACE ?= judge-demo-class
JUDGE_BASE_URL ?= http://$(JUDGE_HOST):$(JUDGE_PORT)
CODE_CATEGORIES := beginner-python-bug-fix
A11Y_CATEGORIES := accessibility/output-format

# Constrained-proxy profile for the M4 Pro sweep. These knobs do NOT turn the
# M4 into a real weak device; they are a comparative stress profile that
# disables the Metal GPU path, restricts threads, and shrinks the KV cache.
# See reports/model_tier_decision_memo.md for the honest framing.
PROXY_NUM_THREAD ?= 4
PROXY_NUM_GPU    ?= 0
PROXY_NUM_CTX    ?= 2048

.PHONY: install install-a11y run run-strong run-weak run-classroom run-school-box judge-demo judge-quickstart setup-semantic preflight repo-check export-local-data label-local-data test smoke-code-runner smoke-retrieval smoke-ocr smoke-a11y release-gate benchmark-inclusive-classroom \
        eval eval-baseline eval-experimental eval-hybrid \
        eval-baseline-code eval-experimental-code eval-hybrid-code \
        eval-code-tutor-abc eval-fullpack \
        eval-fullpack-strong eval-fullpack-weak \
        eval-proxy-e4b eval-proxy-e2b \
        eval-proxy-strong eval-proxy-weak \
        eval-preset-lexical eval-preset-hybrid eval-preset-e4b eval-preset-e2b eval-preset-school-box eval-preset-a11y-smoke \
        eval-weak-a11y-default eval-weak-a11y-tightened eval-weak-a11y-ab \
        eval-weak-fullpack-tightened eval-retrieval-compare \
        eval-tier-sweep report benchmark-summary benchmark-preset school-box-load school-box-demo-proof litert-validation device-tier-comparison judge-bundle

install:
	$(PYTHON) -m pip install -r requirements.txt

install-a11y:
	$(PYTHON) -m pip install -r requirements-a11y.txt

run:
	$(PYTHON) -m uvicorn app.main:app --reload

# Profile-aware run targets. These set ACCESSLAB_DEPLOYMENT_PROFILE for the
# child process so the app boots with the matching default model and the
# status panel/health endpoint correctly report which profile is active.
# ACCESSLAB_MODEL is cleared for these explicit profile targets so they are
# deterministic even if an operator previously pinned a model in .env.
run-strong:
	ACCESSLAB_MODEL= ACCESSLAB_DEPLOYMENT_PROFILE=strong $(PYTHON) -m uvicorn app.main:app --reload

run-weak:
	ACCESSLAB_MODEL= ACCESSLAB_DEPLOYMENT_PROFILE=weak $(PYTHON) -m uvicorn app.main:app --reload

run-classroom:
	ACCESSLAB_DEPLOYMENT_MODE=classroom-local $(PYTHON) -m uvicorn app.main:app --reload

run-school-box:
	ACCESSLAB_DEPLOYMENT_MODE=school-box-shared $(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --reload

judge-demo:
	@if [ ! -x "$(JUDGE_PYTHON)" ]; then python3 -m venv .venv; fi
	$(JUDGE_PYTHON) -m pip install -r requirements.txt
	ACCESSLAB_DATA_DIR="$(JUDGE_DATA_DIR)" \
	ACCESSLAB_DEPLOYMENT_MODE=school-box-shared \
	ACCESSLAB_CLASS_SPACE="$(JUDGE_CLASS_SPACE)" \
	ACCESSLAB_TRAINING_CAPTURE_ENABLED=on \
	$(JUDGE_PYTHON) scripts/seed_judge_demo.py \
		--reset \
		--data-dir "$(JUDGE_DATA_DIR)" \
		--class-space "$(JUDGE_CLASS_SPACE)" \
		--base-url "$(JUDGE_BASE_URL)"
	ACCESSLAB_DATA_DIR="$(JUDGE_DATA_DIR)" \
	ACCESSLAB_DEPLOYMENT_MODE=school-box-shared \
	ACCESSLAB_CLASS_SPACE="$(JUDGE_CLASS_SPACE)" \
	ACCESSLAB_TRAINING_CAPTURE_ENABLED=on \
	$(JUDGE_PYTHON) scripts/run_operator_preflight.py
	@echo "Judge URL: $(JUDGE_BASE_URL)/judge-demo"
	@echo "Proof dashboard: $(JUDGE_BASE_URL)/proofs"
	ACCESSLAB_DATA_DIR="$(JUDGE_DATA_DIR)" \
	ACCESSLAB_DEPLOYMENT_MODE=school-box-shared \
	ACCESSLAB_CLASS_SPACE="$(JUDGE_CLASS_SPACE)" \
	ACCESSLAB_TRAINING_CAPTURE_ENABLED=on \
	$(JUDGE_PYTHON) -m uvicorn app.main:app --host "$(JUDGE_HOST)" --port "$(JUDGE_PORT)"

judge-quickstart: judge-demo

setup-semantic:
	$(PYTHON) scripts/setup_embeddinggemma.py --healthz-url "$(HEALTHZ_URL)"

preflight:
	$(PYTHON) scripts/run_operator_preflight.py

repo-check:
	$(PYTHON) scripts/run_repo_check.py

school-box-load:
	$(PYTHON) scripts/run_school_box_load.py \
		--jobs "$(LOAD_JOBS)" \
		--max-concurrent-jobs "$(LOAD_MAX_CONCURRENT_JOBS)" \
		--device-label "$(DEVICE_LABEL)" \
		--device-tier "school-box-host"

school-box-demo-proof:
	$(PYTHON) scripts/run_school_box_demo_proof.py \
		--max-concurrent-jobs "$(LOAD_MAX_CONCURRENT_JOBS)"

litert-validation:
	$(PYTHON) scripts/run_litert_validation.py

device-tier-comparison:
	$(PYTHON) scripts/build_device_tier_comparison.py $(SUMMARIES)

judge-bundle:
	$(PYTHON) scripts/build_judge_bundle.py

export-local-data:
	$(PYTHON) scripts/export_local_data.py \
		$(if $(EXPORT_OUTPUT),--output "$(EXPORT_OUTPUT)",)

label-local-data:
	@test -n "$(SOURCE_TYPE)" || (echo "Usage: make label-local-data SOURCE_TYPE=qa|code SESSION_ID=<id> QUALITY_LABEL=<label> [LABEL_NOTE='...']" >&2; exit 2)
	@test -n "$(SESSION_ID)" || (echo "SESSION_ID is required." >&2; exit 2)
	@test -n "$(QUALITY_LABEL)" || (echo "QUALITY_LABEL is required." >&2; exit 2)
	$(PYTHON) scripts/label_local_data.py \
		--source-type "$(SOURCE_TYPE)" \
		--id "$(SESSION_ID)" \
		--label "$(QUALITY_LABEL)" \
		$(if $(LABEL_NOTE),--note "$(LABEL_NOTE)",)

test:
	$(PYTHON) -m pytest

smoke-code-runner:
	$(PYTHON) scripts/run_code_runner_hardening_smoke.py

smoke-retrieval:
	$(PYTHON) scripts/run_retrieval_smoke.py \
		$(if $(DOCUMENT),--document "$(DOCUMENT)",) \
		$(if $(QUESTION),--question "$(QUESTION)",) \
		$(if $(EXPECTED_SUBSTRING),--expected-substring "$(EXPECTED_SUBSTRING)",)

smoke-ocr:
	@test -n "$(PDF)" || (echo "Usage: make smoke-ocr PDF=/absolute/path/to/scanned.pdf [QUESTION='...'] [MODEL=...]" >&2; exit 2)
	$(PYTHON) scripts/run_ocr_smoke.py \
		--pdf "$(PDF)" \
		$(if $(QUESTION),--question "$(QUESTION)",) \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(ACCESSLAB_OLLAMA_URL),--ollama-url "$(ACCESSLAB_OLLAMA_URL)",)

smoke-a11y:
	$(PYTHON) scripts/run_accesslab_a11y_smoke.py

release-gate: test smoke-a11y

# Generic eval target (pass any combination of overrides via env vars).
# Prompt-variant defaults: QA=baseline, code=hybrid (set in the harness).
# PROMPT_VARIANT=<x> still works as a legacy override that pins both.
eval:
	$(PYTHON) scripts/run_accesslab_eval.py \
		--device-label "$(DEVICE_LABEL)" \
		--device-tier "$(DEVICE_TIER)" \
		--cold-warm "$(COLD_WARM)" \
		$(if $(RUNTIME_BACKEND),--runtime-backend "$(RUNTIME_BACKEND)",) \
		$(if $(DEPLOYMENT_MODE),--deployment-mode "$(DEPLOYMENT_MODE)",) \
		$(if $(RETRIEVAL_MODE),--retrieval-mode "$(RETRIEVAL_MODE)",) \
		$(if $(PROMPT_VARIANT),--prompt-variant "$(PROMPT_VARIANT)",) \
		$(if $(QA_PROMPT_VARIANT),--qa-prompt-variant "$(QA_PROMPT_VARIANT)",) \
		$(if $(CODE_PROMPT_VARIANT),--code-prompt-variant "$(CODE_PROMPT_VARIANT)",) \
		$(if $(QA_DISCIPLINE_PROFILE),--qa-discipline-profile "$(QA_DISCIPLINE_PROFILE)",) \
		$(if $(RUN_LABEL),--run-label "$(RUN_LABEL)",) \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(NUM_THREAD),--num-thread "$(NUM_THREAD)",) \
		$(if $(NUM_GPU),--num-gpu "$(NUM_GPU)",) \
		$(if $(NUM_CTX),--num-ctx "$(NUM_CTX)",) \
		$(if $(CATEGORIES),--categories "$(CATEGORIES)",)

# Convenience: baseline run (current XML-tag prompts)
# Before a cold run: ollama stop gemma4:e4b
eval-baseline:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="baseline-$(shell date +%Y%m%d)" \
		PROMPT_VARIANT=baseline \
		COLD_WARM="$(COLD_WARM)" \
		$(if $(CATEGORIES),CATEGORIES="$(CATEGORIES)",) \
		$(if $(MODEL),MODEL="$(MODEL)",) \
		$(if $(NUM_THREAD),NUM_THREAD="$(NUM_THREAD)",) \
		$(if $(NUM_GPU),NUM_GPU="$(NUM_GPU)",) \
		$(if $(NUM_CTX),NUM_CTX="$(NUM_CTX)",)

# Convenience: experimental run (lighter colon-prefix prompts)
# Before a cold run: ollama stop gemma4:e4b
eval-experimental:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="exp-lighter-tags-$(shell date +%Y%m%d)" \
		PROMPT_VARIANT=experimental \
		COLD_WARM="$(COLD_WARM)" \
		$(if $(CATEGORIES),CATEGORIES="$(CATEGORIES)",) \
		$(if $(MODEL),MODEL="$(MODEL)",) \
		$(if $(NUM_THREAD),NUM_THREAD="$(NUM_THREAD)",) \
		$(if $(NUM_GPU),NUM_GPU="$(NUM_GPU)",) \
		$(if $(NUM_CTX),NUM_CTX="$(NUM_CTX)",)

# Convenience: hybrid run (XML-anchored code tutor; baseline QA).
# Targets the code-tutor weak spot: strong <patched_code>/<diagnosis>
# anchors, explicit evidence vocabulary, still shorter than baseline.
# Before a cold run: ollama stop gemma4:e4b
eval-hybrid:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="hybrid-code-$(shell date +%Y%m%d)" \
		PROMPT_VARIANT=hybrid \
		COLD_WARM="$(COLD_WARM)" \
		$(if $(CATEGORIES),CATEGORIES="$(CATEGORIES)",) \
		$(if $(MODEL),MODEL="$(MODEL)",) \
		$(if $(NUM_THREAD),NUM_THREAD="$(NUM_THREAD)",) \
		$(if $(NUM_GPU),NUM_GPU="$(NUM_GPU)",) \
		$(if $(NUM_CTX),NUM_CTX="$(NUM_CTX)",)

# Code-only shortcuts: filter to beginner-python-bug-fix category (8 tasks).
# Use these for the A/B/C comparison of the code tutor repair work.
eval-baseline-code:
	$(MAKE) eval-baseline CATEGORIES="$(CODE_CATEGORIES)" DEVICE_LABEL="$(DEVICE_LABEL)"

eval-experimental-code:
	$(MAKE) eval-experimental CATEGORIES="$(CODE_CATEGORIES)" DEVICE_LABEL="$(DEVICE_LABEL)"

eval-hybrid-code:
	$(MAKE) eval-hybrid CATEGORIES="$(CODE_CATEGORIES)" DEVICE_LABEL="$(DEVICE_LABEL)"

# One-shot A/B/C: baseline + experimental + hybrid on code tasks only, then print table.
# Run on the machine where Ollama is listening (see ACCESSLAB_OLLAMA_URL in .env).
eval-code-tutor-abc:
	$(PYTHON) scripts/run_code_tutor_abc_benchmark.py \
		--device-label "$(DEVICE_LABEL)" \
		--device-tier "$(DEVICE_TIER)" \
		--cold-warm "$(COLD_WARM)" \
		$(if $(MODEL),--model "$(MODEL)",) \
		$(if $(ACCESSLAB_OLLAMA_URL),--ollama-url "$(ACCESSLAB_OLLAMA_URL)",)

# Full 20-task confirmation run with the new defaults (QA=baseline,
# code-tutor=hybrid). Use this to confirm the app still behaves end-to-end
# after promoting hybrid as the code-tutor default.
eval-fullpack:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="fullpack-defaults-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		$(if $(MODEL),MODEL="$(MODEL)",)

# Profile-pinned full-pack runs. These hard-pin the model so the run label
# clearly reflects the deployment profile being benchmarked, regardless of
# what is in the operator's .env. Reference (unconstrained) configuration:
# Metal GPU on, no num_thread/num_ctx caps. Use eval-proxy-{strong,weak} for
# the constrained-proxy companion runs.
eval-fullpack-strong:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="fullpack-strong-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e4b

eval-fullpack-weak:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="fullpack-weak-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e2b

# Constrained-proxy convenience targets. Pin the model and apply the
# PROXY_NUM_* knobs. Run label and device tier are tagged 'proxy'.
eval-proxy-e4b:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		DEVICE_TIER=proxy \
		RUN_LABEL="proxy-e4b-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e4b \
		NUM_THREAD="$(PROXY_NUM_THREAD)" \
		NUM_GPU="$(PROXY_NUM_GPU)" \
		NUM_CTX="$(PROXY_NUM_CTX)"

eval-proxy-e2b:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		DEVICE_TIER=proxy \
		RUN_LABEL="proxy-e2b-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e2b \
		NUM_THREAD="$(PROXY_NUM_THREAD)" \
		NUM_GPU="$(PROXY_NUM_GPU)" \
		NUM_CTX="$(PROXY_NUM_CTX)"

# Profile aliases for the constrained-proxy targets. strong == e4b, weak ==
# e2b, matching the profile mapping in app/config.py. Kept as aliases so
# existing eval-proxy-e4b/e2b targets continue to work.
eval-proxy-strong: eval-proxy-e4b
eval-proxy-weak: eval-proxy-e2b

eval-preset-lexical:
	$(MAKE) eval DEVICE_LABEL="$(DEVICE_LABEL)" RUN_LABEL="preset-lexical-$(shell date +%Y%m%d)" RETRIEVAL_MODE=lexical

eval-preset-hybrid:
	$(MAKE) eval DEVICE_LABEL="$(DEVICE_LABEL)" RUN_LABEL="preset-hybrid-$(shell date +%Y%m%d)" RETRIEVAL_MODE=hybrid

eval-preset-e4b:
	$(MAKE) eval-fullpack-strong DEVICE_LABEL="$(DEVICE_LABEL)"

eval-preset-e2b:
	$(MAKE) eval-fullpack-weak DEVICE_LABEL="$(DEVICE_LABEL)"

eval-preset-school-box:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		DEVICE_TIER=school-box-host \
		DEPLOYMENT_MODE=school-box-shared \
		RUN_LABEL="preset-school-box-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		RETRIEVAL_MODE="$(if $(RETRIEVAL_MODE),$(RETRIEVAL_MODE),hybrid)" \
		$(if $(MODEL),MODEL="$(MODEL)",)

eval-preset-a11y-smoke:
	$(MAKE) smoke-a11y

# Weak-tier accessibility/output-format A/B targets. These run the 4 a11y
# tasks against gemma4:e2b under the constrained-proxy profile to isolate
# the effect of the WEAK_TIER_QA_DISCIPLINE_SUFFIX (see app/services/qa.py).
# Use them in pairs to compare "default" vs "weak" QA discipline on the
# weak-tier model with everything else held constant.
eval-weak-a11y-default:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		DEVICE_TIER=proxy \
		RUN_LABEL="weak-a11y-default-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e2b \
		QA_DISCIPLINE_PROFILE=default \
		CATEGORIES="$(A11Y_CATEGORIES)" \
		NUM_THREAD="$(PROXY_NUM_THREAD)" \
		NUM_GPU="$(PROXY_NUM_GPU)" \
		NUM_CTX="$(PROXY_NUM_CTX)"

eval-weak-a11y-tightened:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		DEVICE_TIER=proxy \
		RUN_LABEL="weak-a11y-tightened-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e2b \
		QA_DISCIPLINE_PROFILE=weak \
		CATEGORIES="$(A11Y_CATEGORIES)" \
		NUM_THREAD="$(PROXY_NUM_THREAD)" \
		NUM_GPU="$(PROXY_NUM_GPU)" \
		NUM_CTX="$(PROXY_NUM_CTX)"

# One-shot accessibility A/B: runs default then tightened back-to-back.
# Both summaries land in reports/runs/; pair them with
# scripts/compare_benchmark_runs.py for the decision memo.
eval-weak-a11y-ab: eval-weak-a11y-default eval-weak-a11y-tightened

# Reproducible retrieval comparison on the grounded-QA subset. This keeps
# the model fixed while toggling lexical-only vs hybrid retrieval so judges
# can compare SQLite FTS5 alone against SQLite FTS5 + EmbeddingGemma.
eval-retrieval-compare:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="retrieval-lexical-$(shell date +%Y%m%d)" \
		CATEGORIES="worksheet/local-doc,accessibility/output-format" \
		RETRIEVAL_MODE=lexical \
		$(if $(MODEL),MODEL="$(MODEL)",)
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="retrieval-semantic-$(shell date +%Y%m%d)" \
		CATEGORIES="worksheet/local-doc,accessibility/output-format" \
		RETRIEVAL_MODE=semantic \
		$(if $(MODEL),MODEL="$(MODEL)",)
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		RUN_LABEL="retrieval-hybrid-$(shell date +%Y%m%d)" \
		CATEGORIES="worksheet/local-doc,accessibility/output-format" \
		RETRIEVAL_MODE=hybrid \
		$(if $(MODEL),MODEL="$(MODEL)",)

# Full 20-task confirmation run for weak-tier with the discipline suffix on,
# under the constrained-proxy profile. Use this AFTER the focused a11y A/B
# shows improvement to confirm the rest of the pack did not regress.
eval-weak-fullpack-tightened:
	$(MAKE) eval \
		DEVICE_LABEL="$(DEVICE_LABEL)" \
		DEVICE_TIER=proxy \
		RUN_LABEL="weak-fullpack-tightened-$(shell date +%Y%m%d)" \
		COLD_WARM="$(COLD_WARM)" \
		MODEL=gemma4:e2b \
		QA_DISCIPLINE_PROFILE=weak \
		NUM_THREAD="$(PROXY_NUM_THREAD)" \
		NUM_GPU="$(PROXY_NUM_GPU)" \
		NUM_CTX="$(PROXY_NUM_CTX)"

# One-shot model-tier sweep. Runs four full-pack benchmarks (e4b reference,
# e2b reference, e4b proxy, e2b proxy) and prints a comparison table.
eval-tier-sweep:
	$(PYTHON) scripts/run_model_tier_sweep.py \
		--device-label "$(DEVICE_LABEL)" \
		--cold-warm "$(COLD_WARM)" \
		--proxy-num-thread "$(PROXY_NUM_THREAD)" \
		--proxy-num-gpu "$(PROXY_NUM_GPU)" \
		--proxy-num-ctx "$(PROXY_NUM_CTX)" \
		$(if $(ACCESSLAB_OLLAMA_URL),--ollama-url "$(ACCESSLAB_OLLAMA_URL)",)

report:
	$(PYTHON) scripts/build_accesslab_report.py $(SUMMARIES)

benchmark-summary:
	$(PYTHON) scripts/build_benchmark_summary.py $(SUMMARIES)

benchmark-preset:
	@test -n "$(PRESET)" || (echo "Usage: make benchmark-preset PRESET=grounded-qa-hybrid-e4b [DEVICE_LABEL=...]" >&2; exit 2)
	$(PYTHON) scripts/run_benchmark_preset.py \
		--preset "$(PRESET)" \
		--device-label "$(DEVICE_LABEL)" \
		--cold-warm "$(COLD_WARM)"

benchmark-inclusive-classroom:
	$(MAKE) benchmark-preset PRESET=inclusive-classroom-smoke DEVICE_LABEL="$(DEVICE_LABEL)"
	$(MAKE) benchmark-preset PRESET=inclusive-school-box-stress DEVICE_LABEL="$(DEVICE_LABEL)"
