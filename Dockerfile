# OpenClaw + vLLM in Docker (GPU). Базовый образ runpod/pytorch — удобен и локально, и в облаке.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

LABEL org.opencontainers.image.title="guildclaw"
LABEL org.opencontainers.image.description="Guildclaw: OpenClaw + vLLM (NVIDIA GPU, Docker)"

ENV DEBIAN_FRONTEND=noninteractive
ENV HF_HOME=/workspace/huggingface
ENV OPENCLAW_WORKSPACE=/workspace/openclaw

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    jq \
    lsof \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && npm install -g npm@latest

RUN pip install --no-cache-dir vllm

ARG OPENCLAW_VERSION=latest
RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

RUN mkdir -p /workspace/huggingface \
    /workspace/.openclaw \
    /workspace/openclaw

COPY entrypoint-common.sh /opt/openclaw/entrypoint-common.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /opt/openclaw/entrypoint-common.sh

COPY workspace/ /workspace/openclaw/

EXPOSE 8000 18789 18790 18793

ENV VLLM_API_KEY=changeme
ENV OPENCLAW_WEB_PASSWORD=changeme
ENV MODEL_NAME=Qwen/Qwen2.5-Coder-7B-Instruct
ENV SERVED_MODEL_NAME=local-coder
ENV MAX_MODEL_LEN=16384
ENV GPU_MEMORY_UTILIZATION=0.90
ENV TOOL_CALL_PARSER=hermes
ENV TENSOR_PARALLEL_SIZE=auto

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
