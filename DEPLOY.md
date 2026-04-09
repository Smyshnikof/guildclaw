# Деплой: Guildclaw (OpenClaw + llama.cpp GGUF)

**Guildclaw** — один образ: **OpenClaw**, **llama-server** (llama.cpp, OpenAI-совместимый API на порту **8000**) и **Model Hub** — веб-UI на **8080** для скачивания **.gguf**, активации и удаления моделей.

Модели **только для LLM** (чат/код), без диффузии.

---

## Локальный запуск

```bash
docker build -t youruser/guildclaw:latest .
```

```bash
docker run --gpus all \
  -e LLAMA_API_KEY="секрет-api" \
  -e OPENCLAW_WEB_PASSWORD="секрет-ui" \
  -e GUILDCLAW_HUB_TOKEN="секрет-хаб" \
  -e HF_TOKEN="" \
  -p 8000:8000 -p 8080:8080 -p 18789:18789 -p 18790:18790 -p 18793:18793 \
  -v guildclaw_data:/workspace \
  youruser/guildclaw:latest
```

- **Model Hub:** `http://localhost:8080/?token=<GUILDCLAW_HUB_TOKEN>` (если токен задан; иначе без query). Токен Hub и опционально HF можно **сохранить в браузере** (блок «Токены» или страница входа при 401) — как в Control UI, без вечного `?token=` в закладке. Интерфейс: вкладки **Пресеты**, **HuggingFace**, **Мои GGUF** (активация / удаление).
- **OpenClaw UI:** `http://localhost:18789/?token=<OPENCLAW_WEB_PASSWORD>`
- **LLM API:** `http://localhost:8000/v1`

Порядок: зайти в Hub → скачать пресет или вставить прямой URL на `.gguf` → **Активировать** → подождать перезапуск `llama-server` → пользоваться OpenClaw. Поле `primary` в `openclaw.json` синхронизируется с активной моделью (провайдер `local-llama`, id = `SERVED_MODEL_NAME` / запись в `active.json`).

Файлы GGUF: `/workspace/models/gguf/`. Состояние: `/workspace/.guildclaw/active.json`.

---

## Сборка образа (GitHub Actions)

`llama-server` с CUDA берётся **готовым** из [`ghcr.io/ggml-org/llama.cpp:server-cuda`](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md) — **без** компиляции llama.cpp в CI (значительно быстрее). Другой вариант CUDA: `--build-arg LLAMA_SERVER_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda13`. Таймаут workflow **180** минут остаётся с запасом.

Secrets: `DOCKERHUB_TOKEN`, variable `DOCKERHUB_USERNAME`. Workflow **Build and push guildclaw**.

---

## RunPod

Том на **`/workspace`** (50+ GB рекомендуется под GGUF).

### Порты

| Порт  | Сервис |
| ----- | ------ |
| 22    | SSH    |
| 8000  | llama-server (OpenAI API) |
| 8080  | Model Hub (каталог / URL / удаление) |
| 18789 | OpenClaw gateway |
| 18790 | OpenClaw Bridge |
| 18793 | OpenClaw Canvas |

### Переменные окружения

| Переменная | Описание |
| ---------- | -------- |
| `LLAMA_API_KEY` | Ключ для API llama-server (`Authorization: Bearer`) |
| `OPENCLAW_WEB_PASSWORD` | Токен Web UI OpenClaw |
| `GUILDCLAW_HUB_TOKEN` | **Рекомендуется:** токен для Model Hub (иначе UI/API без защиты) |
| `SERVED_MODEL_NAME` | Alias модели в API и в OpenClaw (по умолчанию `local-gguf`) |
| `LLAMA_CTX_SIZE` | Контекст (по умолчанию 8192) |
| `LLAMA_N_GPU_LAYERS` | Слоёв на GPU (99 ≈ максимум доступных) |
| `LLAMA_SERVER_EXTRA_ARGS` | Доп. флаги `llama-server` (строка) |
| `HF_TOKEN` | Для загрузок с Hugging Face (gated / лимиты) |
| `GUILDCLAW_BOOTSTRAP_GGUF` | `1` (по умолчанию): если нет валидного `active.json`, скачать дефолтный GGUF и активировать. `0` — только Hub вручную |
| `GUILDCLAW_DEFAULT_GGUF_URL` | URL дефолтного `.gguf` (по умолчанию Gemma 4 E4B Q4_K_M с HF) |
| `GUILDCLAW_DEFAULT_GGUF_FILENAME` | Имя файла в `/workspace/models/gguf/` |
| `TELEGRAM_BOT_TOKEN` | Опционально |
| `OPENCLAW_CONTROL_UI_ALLOWED_ORIGINS` | Доп. origin для Control UI (через запятую), если заходите не с RunPod-прокси |
| `OPENCLAW_CONTROL_UI_ALLOW_ANY` | `1` / `true` — `allowedOrigins: ["*"]` (проще, но слабее с точки зрения безопасности) |

Переменная **`RUNPOD_POD_ID`** задаётся RunPod сама; в `openclaw.json` автоматически добавляется `https://<pod>-18789.proxy.runpod.net` в `gateway.controlUi.allowedOrigins` перед стартом шлюза.

Совместимость: если в образе **`LLAMA_API_KEY=changeme`**, а вы задали только **`VLLM_API_KEY`** (как в старых шаблонах), он **подставится** и в llama-server, и в `openclaw.json` после синка. Явно задайте **`LLAMA_API_KEY`**, если нужен отдельный ключ только для LLM API.

### URL на RunPod

- Hub: `https://<pod-id>-8080.proxy.runpod.net/?token=<GUILDCLAW_HUB_TOKEN>`
- OpenClaw: `https://<pod-id>-18789.proxy.runpod.net/?token=<OPENCLAW_WEB_PASSWORD>`

---

## Каталог «популярных» моделей

Редактируйте [`model_hub/catalog.json`](model_hub/catalog.json) в репозитории и пересоберите образ, либо монтируйте свой файл в `/opt/guildclaw/model_hub/catalog.json`.

---

## RTX 50 / sm_120

Образ собирается с `CMAKE_CUDA_ARCHITECTURES` без **120** (ограничения CUDA 12.4 в базе). Для нативного Blackwell пересоберите Dockerfile с архитектурой **120** и подходящей базой CUDA.

---

## Про `a2go-main`

Папка `a2go-main` при желании — отдельный апстрим; Guildclaw на неё не завязан.
