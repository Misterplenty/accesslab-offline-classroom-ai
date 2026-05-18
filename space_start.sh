#!/usr/bin/env sh
set -eu

export PORT="${PORT:-7860}"
export OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1:11434}"
export ACCESSLAB_OLLAMA_URL="${ACCESSLAB_OLLAMA_URL:-http://127.0.0.1:11434}"
export ACCESSLAB_DEPLOYMENT_PROFILE="${ACCESSLAB_DEPLOYMENT_PROFILE:-weak}"
export ACCESSLAB_MODEL="${ACCESSLAB_MODEL:-gemma4:e2b}"
export ACCESSLAB_DEPLOYMENT_MODE="${ACCESSLAB_DEPLOYMENT_MODE:-school-box-shared}"
export ACCESSLAB_CLASS_SPACE="${ACCESSLAB_CLASS_SPACE:-judge-demo-class}"
export ACCESSLAB_SEMANTIC_ENABLED="${ACCESSLAB_SEMANTIC_ENABLED:-off}"
export ACCESSLAB_SEMANTIC_MODEL="${ACCESSLAB_SEMANTIC_MODEL:-embeddinggemma}"
export ACCESSLAB_OCR_ENABLED="${ACCESSLAB_OCR_ENABLED:-off}"
export ACCESSLAB_AUTO_INSTALL_OCR_REQUIREMENTS="${ACCESSLAB_AUTO_INSTALL_OCR_REQUIREMENTS:-off}"
export ACCESSLAB_LLM_TIMEOUT_SECONDS="${ACCESSLAB_LLM_TIMEOUT_SECONDS:-300}"
export ACCESSLAB_DATA_DIR="${ACCESSLAB_DATA_DIR:-/tmp/accesslab-data}"

mkdir -p "$ACCESSLAB_DATA_DIR"

ollama serve &
OLLAMA_PID="$!"

cleanup() {
    kill "$OLLAMA_PID" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(
    echo "Preparing Ollama on $ACCESSLAB_OLLAMA_URL ..."
    for _ in $(seq 1 90); do
        if curl -fsS "$ACCESSLAB_OLLAMA_URL/api/tags" >/dev/null; then
            break
        fi
        sleep 1
    done

    if curl -fsS "$ACCESSLAB_OLLAMA_URL/api/tags" >/dev/null; then
        if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fx "$ACCESSLAB_MODEL" >/dev/null; then
            echo "Pulling $ACCESSLAB_MODEL ..."
            ollama pull "$ACCESSLAB_MODEL"
        fi

        if [ "$ACCESSLAB_SEMANTIC_ENABLED" != "off" ]; then
            if ! ollama list | awk 'NR > 1 {print $1}' | grep -Fx "$ACCESSLAB_SEMANTIC_MODEL" >/dev/null; then
                echo "Pulling $ACCESSLAB_SEMANTIC_MODEL ..."
                ollama pull "$ACCESSLAB_SEMANTIC_MODEL"
            fi
        fi
    else
        echo "Ollama did not become ready during startup; AccessLab will report that in /healthz."
    fi
) &

echo "Starting AccessLab on 0.0.0.0:$PORT ..."
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
