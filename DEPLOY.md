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

- **Model Hub:** `http://localhost:8080/?token=<GUILDCLAW_HUB_TOKEN>` (если токен задан; иначе UI без query).
- **OpenClaw UI:** `http://localhost:18789/?token=<OPENCLAW_WEB_PASSWORD>`
- **LLM API:** `http://localhost:8000/v1`

Порядок: зайти в Hub → скачать пресет или вставить прямой URL на `.gguf` → **Активировать** → подождать перезапуск `llama-server` → пользоваться OpenClaw. Поле `primary` в `openclaw.json` синхронизируется с активной моделью (провайдер `local-llama`, id = `SERVED_MODEL_NAME` / запись в `active.json`).

Файлы GGUF: `/workspace/models/gguf/`. Состояние: `/workspace/.guildclaw/active.json`.

---

## Сборка образа (GitHub Actions)

Сборка **долгая** (компиляция llama.cpp + CUDA). В workflow выставлен таймаут **180** минут.

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
| `TELEGRAM_BOT_TOKEN` | Опционально |

Совместимость: **`VLLM_API_KEY`** в окружении всё ещё подхватывается как **`LLAMA_API_KEY`**, если последний не задан.

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
