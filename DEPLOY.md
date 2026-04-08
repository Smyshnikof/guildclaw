# Деплой: Guildclaw (OpenClaw + vLLM в Docker)

**Guildclaw** — имя проекта и тег Docker-образа (`guildclaw`). Один образ для **локальной машины** (Linux/WSL2 с NVIDIA Container Toolkit или Docker Desktop + GPU) и для **RunPod** и любых других хостингов, где есть Docker и NVIDIA драйвер.

База `runpod/pytorch` — это просто готовый CUDA+PyTorch слой; ограничения только в том, что нужна **Linux-контейнер** и **GPU** (vLLM без GPU в этом образе не настраивался).

---

## Локальный запуск

Соберите образ или возьмите с Docker Hub после CI.

```bash
docker build -t youruser/guildclaw:latest .
```

Запуск с томом под модели и кэш Hugging Face:

```bash
docker run --gpus all \
  -e VLLM_API_KEY="секрет-для-api" \
  -e OPENCLAW_WEB_PASSWORD="секрет-для-ui" \
  -e HF_TOKEN="" \
  -p 8000:8000 -p 18789:18789 -p 18790:18790 -p 18793:18793 \
  -v openclaw_workspace:/workspace \
  youruser/guildclaw:latest
```

После старта vLLM и gateway:

- **OpenClaw Web UI:** `http://localhost:18789/?token=<OPENCLAW_WEB_PASSWORD>`
- **API модели (OpenAI-совместимый):** `http://localhost:8000/v1`

На Windows используйте Docker Desktop с включённой поддержкой GPU и WSL2 backend, либо запускайте из WSL2.

---

## Сборка и публикация (GitHub Actions)

1. Корень репозитория — эта папка.
2. **Secret** `DOCKERHUB_TOKEN`, **Variable** (или secret) `DOCKERHUB_USERNAME`.
3. Workflow **Build and push guildclaw**.

Образ: `<dockerhub_user>/guildclaw:<тег>`.

Сборка вручную и push:

```bash
docker buildx build --platform linux/amd64 -t youruser/guildclaw:latest --push .
```

---

## RunPod (опционально)

1. В [`runpod-template.json`](runpod-template.json) подставьте свой Docker Hub user в `imageName`.
2. Template: образ, переменные из JSON, **volume** с mount **`/workspace`** (желательно 50+ GB).

### Порты

| Порт  | Назначение            |
| ----- | --------------------- |
| 22    | SSH (как настроит RunPod) |
| 8000  | vLLM API `/v1`        |
| 18789 | OpenClaw gateway / UI |
| 18790 | OpenClaw Bridge       |
| 18793 | OpenClaw Canvas       |

### Переменные окружения

| Переменная                | Обязательно | Описание |
| ------------------------- | ----------- | -------- |
| `VLLM_API_KEY`            | Да          | Ключ для vLLM |
| `OPENCLAW_WEB_PASSWORD`   | Да          | Токен Web UI / gateway (`?token=` в URL) |
| `MODEL_NAME`              | Нет         | Hugging Face id для `vllm serve` |
| `SERVED_MODEL_NAME`       | Нет         | Имя в OpenAI API |
| `HF_TOKEN`                | Нет         | Gated-модели и HF |
| `TELEGRAM_BOT_TOKEN`      | Нет         | Telegram-канал |

Альтернатива токену UI: **`A2GO_AUTH_TOKEN`** — entrypoint воспринимает его как `OPENCLAW_WEB_PASSWORD`.

Дополнительно: `MAX_MODEL_LEN`, `GPU_MEMORY_UTILIZATION`, `TOOL_CALL_PARSER`, `TENSOR_PARALLEL_SIZE`.

### URL на RunPod

- Web UI: `https://<pod-id>-18789.proxy.runpod.net/?token=<OPENCLAW_WEB_PASSWORD>`
- API: `https://<pod-id>-8000.proxy.runpod.net/v1`

### Pairing

По SSH: `openclaw devices list`, затем `openclaw devices approve <requestId>`.

Безопасность: [trust.openclaw.ai](https://trust.openclaw.ai).

---

## Про `a2go-main`

Папка `a2go-main` (если лежит рядом) — отдельный апстрим agent2go. Этот проект **не зависит** от него.
