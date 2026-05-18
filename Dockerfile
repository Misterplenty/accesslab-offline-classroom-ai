FROM ollama/ollama:latest

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PORT=7860 \
    OLLAMA_HOST=127.0.0.1:11434 \
    ACCESSLAB_OLLAMA_URL=http://127.0.0.1:11434 \
    ACCESSLAB_DEPLOYMENT_PROFILE=weak \
    ACCESSLAB_MODEL=gemma4:e2b \
    ACCESSLAB_DEPLOYMENT_MODE=school-box-shared \
    ACCESSLAB_CLASS_SPACE=judge-demo-class \
    ACCESSLAB_SEMANTIC_ENABLED=off \
    ACCESSLAB_OCR_ENABLED=off \
    ACCESSLAB_AUTO_INSTALL_OCR_REQUIREMENTS=off \
    ACCESSLAB_LLM_TIMEOUT_SECONDS=300 \
    ACCESSLAB_DATA_DIR=/tmp/accesslab-data

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements*.txt /app/
RUN python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY . /app
RUN chmod +x /app/space_start.sh

# Bake the small Gemma 4 profile into the image so a sleeping Space can
# restart without redownloading the model before judges see the demo.
ARG ACCESSLAB_BAKE_MODEL=gemma4:e2b
RUN set -eux; \
    ollama serve >/tmp/ollama-build.log 2>&1 & \
    OLLAMA_PID="$!"; \
    for _ in $(seq 1 90); do \
        if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; then \
            break; \
        fi; \
        sleep 1; \
    done; \
    curl -fsS http://127.0.0.1:11434/api/tags >/dev/null; \
    ollama pull "$ACCESSLAB_BAKE_MODEL"; \
    kill "$OLLAMA_PID"

EXPOSE 7860

ENTRYPOINT []
CMD ["sh", "/app/space_start.sh"]
