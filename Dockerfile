# Guildclaw: OpenClaw + llama.cpp (llama-server) + веб-хаб выбора GGUF.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

LABEL org.opencontainers.image.title="guildclaw"
LABEL org.opencontainers.image.description="Guildclaw: OpenClaw + llama.cpp GGUF + Model Hub (NVIDIA GPU)"

ENV DEBIAN_FRONTEND=noninteractive
ENV HF_HOME=/workspace/huggingface
ENV OPENCLAW_WORKSPACE=/workspace/openclaw

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    git \
    jq \
    lsof \
    cmake \
    build-essential \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

# llama-server с CUDA (архитектуры для большинства потребительских GPU; при необходимости пересоберите образ).
ARG LLAMA_CPP_REF=b8295
RUN git clone --depth 1 --branch "${LLAMA_CPP_REF}" https://github.com/ggml-org/llama.cpp.git /tmp/llama.cpp \
    && cd /tmp/llama.cpp \
    && cmake -B build -G Ninja \
        -DGGML_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES="75;80;86;89;90;100" \
        -DLLAMA_BUILD_TESTS=OFF \
        -DCMAKE_BUILD_TYPE=Release \
    && cmake --build build -j 2 --target llama-server \
    && cp build/bin/llama-server /usr/local/bin/ \
    && rm -rf /tmp/llama.cpp

# Не делать npm install -g npm@latest — NodeSource ломается.
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && node --version && npm --version

ARG OPENCLAW_VERSION=latest
RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

COPY model_hub/requirements.txt /opt/guildclaw/model_hub/requirements.txt
RUN pip install --no-cache-dir -r /opt/guildclaw/model_hub/requirements.txt

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
