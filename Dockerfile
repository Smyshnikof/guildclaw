# Guildclaw: OpenClaw + llama-server (CUDA) + Model Hub.
# llama-server берётся готовым из образа ggml-org (без cmake/nvcc в CI — сборка в разы быстрее).
# Документация образов: https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md
ARG LLAMA_SERVER_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda
FROM ${LLAMA_SERVER_IMAGE}

LABEL org.opencontainers.image.title="guildclaw"
LABEL org.opencontainers.image.description="Guildclaw: OpenClaw + llama.cpp GGUF + Model Hub (NVIDIA GPU)"

ENV DEBIAN_FRONTEND=noninteractive
ENV HF_HOME=/workspace/huggingface
ENV OPENCLAW_WORKSPACE=/workspace/openclaw

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    wget \
    git \
    jq \
    lsof \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Не делать npm install -g npm@latest — NodeSource ломается.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && node --version && npm --version

# Бинарь и *.so (libmtmd, ggml-cuda и др.) лежат в /app у ggml-org; иначе при запуске из PATH — «libmtmd.so.0: not found».
ENV LLAMA_SERVER_BIN=/app/llama-server
RUN ln -sf /app/llama-server /usr/local/bin/llama-server \
    && printf '%s\n' /app >> /etc/ld.so.conf.d/llama-ggml.conf \
    && if [ -d /app/lib ]; then printf '%s\n' /app/lib >> /etc/ld.so.conf.d/llama-ggml.conf; fi \
    && ldconfig

ARG OPENCLAW_VERSION=latest
RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

COPY model_hub/requirements.txt /opt/guildclaw/model_hub/requirements.txt
RUN pip install --no-cache-dir --break-system-packages -r /opt/guildclaw/model_hub/requirements.txt

RUN mkdir -p /workspace/huggingface \
    /workspace/.openclaw \
    /workspace/openclaw \
    /workspace/models/gguf \
    /workspace/.guildclaw

COPY model_hub/ /opt/guildclaw/model_hub/
COPY scripts/sync_openclaw_llama.py /opt/guildclaw/sync_openclaw_llama.py
RUN chmod +x /opt/guildclaw/sync_openclaw_llama.py

COPY entrypoint-common.sh /opt/openclaw/entrypoint-common.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /opt/openclaw/entrypoint-common.sh

COPY workspace/ /workspace/openclaw/

EXPOSE 8000 8080 18789 18790 18793

ENV LLAMA_API_KEY=changeme
ENV OPENCLAW_WEB_PASSWORD=changeme
ENV SERVED_MODEL_NAME=local-gguf
ENV LLAMA_CTX_SIZE=8192
ENV LLAMA_N_GPU_LAYERS=99
ENV GUILDCLAW_HUB_TOKEN=""
ENV LLAMA_SERVER_EXTRA_ARGS=""

# Совместимость со старым шаблоном RunPod
ENV VLLM_API_KEY=changeme

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://localhost:8080/health || exit 1

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
