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
  -p 8000:8000 -p 8080:8080 -p 8081:8081 -p 8888:8888 -p 18789:18789 -p 18790:18790 -p 18793:18793 \
  -v guildclaw_data:/workspace \
  youruser/guildclaw:latest
```

- **Model Hub:** `http://localhost:8080/?token=<GUILDCLAW_HUB_TOKEN>` (если токен задан; иначе без query). Токен Hub и опционально HF можно **сохранить в браузере** (блок «Токены» или страница входа при 401) — как в Control UI, без вечного `?token=` в закладке. Интерфейс: вкладки **Пресеты**, **HuggingFace**, **Мои GGUF** (активация / удаление).
- **Pairing dashboard (:8081):** только **node pairing** (удалённые ноды OpenClaw). Очередь **device** (браузер, CLI, ключ `pairing_ws_device.json`) — через **OpenClaw UI :18789** или `openclaw devices …`, не через :8081. Два paired operator (браузер + сервис :8081) — обычно нормально. Секрет: **`GUILDCLAW_PAIRING_DASH_TOKEN`**, если задан; иначе используется **`OPENCLAW_WEB_PASSWORD`**. WS-handshake с **Ed25519 device** (файл **`$GUILDCLAW_STATE_DIR/pairing_ws_device.json`**, иначе **`/workspace/.guildclaw/`**), иначе шлюз OpenClaw обнуляет scopes и будет «missing scope: operator.pairing». Пока шлюз не поднят, страница покажет ошибку подключения.
- **OpenClaw UI:** `http://localhost:18789/?token=<OPENCLAW_WEB_PASSWORD>`
- **LLM API:** `http://localhost:8000/v1`
- **JupyterLab:** `http://localhost:8888/lab` — при заданном токене: `…/lab?token=<секрет>`. Токен: **`GUILDCLAW_JUPYTER_TOKEN`**, иначе подставляется **`ACCESS_PASSWORD`** (как в шаблоне ComfyUI/RunPod). Отключить: **`GUILDCLAW_JUPYTER=0`**. Рабочая директория по умолчанию: **`/workspace`**. Лог: `/workspace/logs/jupyterlab.log`.

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
| 8081  | Pairing dashboard (node.pair.* через локальный WS к шлюзу) |
| 8888  | JupyterLab (ноутбуки, терминал в `/workspace`) |
| 18789 | OpenClaw gateway |
| 18790 | OpenClaw Bridge |
| 18793 | OpenClaw Canvas |

### Переменные окружения

| Переменная | Описание |
| ---------- | -------- |
| `LLAMA_API_KEY` | Ключ для API llama-server (`Authorization: Bearer`) |
| `OPENCLAW_WEB_PASSWORD` | Токен Web UI OpenClaw |
| `GUILDCLAW_HUB_TOKEN` | **Рекомендуется:** токен для Model Hub (иначе UI/API без защиты) |
| `GUILDCLAW_PAIRING_DASH_TOKEN` | Опционально: отдельный секрет для Pairing dashboard (`:8081`); если пусто — для доступа к дашборду используется `OPENCLAW_WEB_PASSWORD` |
| `GUILDCLAW_JUPYTER` | `1` (по умолчанию): запускать JupyterLab на **8888**. `0` — не запускать |
| `GUILDCLAW_JUPYTER_TOKEN` | Токен входа в JupyterLab (`?token=…`). Если пусто, используется **`ACCESS_PASSWORD`** (совместимость с шаблоном ComfyUI/RunPod). Если оба пусты — Lab без токена (**не рекомендуется** на публичном прокси) |
| `ACCESS_PASSWORD` | Опционально: общий пароль/токен для RunPod-шаблонов; при отсутствии `GUILDCLAW_JUPYTER_TOKEN` подставляется в JupyterLab |
| `SERVED_MODEL_NAME` | Явный **alias** в API/OpenClaw; значение **`local-gguf`** (по умолчанию) значит *авто*: id строится из имени файла как `local-<slug>-gguf` (например `gemma-4-E4B-it-Q4_K_M.gguf` → `local-gemma-4-e4b-it-q4-k-m-gguf`). Любой другой непустой текст — зафиксированный id |
| `LLAMA_CTX_SIZE` | Размер контекста для **llama-server** (`-c`) и поля `contextWindow` в OpenClaw (по умолчанию **16384**). Значения **ниже 16000** автоматически поднимаются до **16000**: иначе агент OpenClaw падает с «Model context window too small … Minimum is 16000». |
| `OPENCLAW_AGENT_MIN_CTX` | Нижняя граница для clamp (по умолчанию `16000`); менять только если апстрим OpenClaw изменит требование |
| `OPENCLAW_COMPACTION_RESERVE_TOKENS_FLOOR` | Минимум зарезервированных токенов под компакцию диалога в `agents.defaults.compaction.reserveTokensFloor` (по умолчанию **20000**). Меньше — OpenClaw может сбрасывать чат с «Context limit exceeded…» |
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
- Pairing: `https://<pod-id>-8081.proxy.runpod.net/?token=<GUILDCLAW_PAIRING_DASH_TOKEN_или_OPENCLAW_WEB_PASSWORD>`
- JupyterLab: `https://<pod-id>-8888.proxy.runpod.net/lab?token=<GUILDCLAW_JUPYTER_TOKEN_или_ACCESS_PASSWORD>`
- OpenClaw: `https://<pod-id>-18789.proxy.runpod.net/?token=<OPENCLAW_WEB_PASSWORD>`

Откройте порты **8081** и **8888** в настройках пода RunPod (HTTP/TCP), если соответствующие прокси не открываются.

### Pod, браузер и «device» для Pairing dashboard

Здесь две разные вещи, их не путайте:

1. **Ваш браузер** — вы только открываете **HTTPS на порт 8081** (страница со списком и кнопками). Это обычный HTTP; токен в URL / Bearer защищает именно **дашборд**, а не WebSocket шлюза OpenClaw. Браузер **не** подключается к `wss://…18789` и **не** является тем «device», о котором говорит протокол шлюза.

2. **Device для WS** — это **процесс Pairing dashboard внутри пода**: он сам ходит на **`ws://127.0.0.1:18789`**, держит ключ Ed25519 в файле **`/workspace/.guildclaw/pairing_ws_device.json`** (на том же томе, что и модели, если вы монтируете `/workspace`). После первого успешного запуска ключ **сохраняется**; пересоздавать его из браузера не нужно. Путь можно переопределить: **`GUILDCLAW_PAIRING_DEVICE_JSON`**.

3. Если шлюз OpenClaw **впервые** видит этот ключ и просит одобрить **device pairing** (редко на loopback, но возможно): зайдите в **OpenClaw Web UI того же пода** (`https://<pod>-18789…` с `OPENCLAW_WEB_PASSWORD`) как оператор и одобрите запрос — это одобрение относится к **«бэкенду дашборда в поде»**, а не к вашему домашнему ПК.

4. **Node pairing** (список на странице :8081) — это уже про **удалённые ноды** (телефон, планшет, другой клиент OpenClaw). Их вы как раз одобряете/отклоняете в этом UI; это не то же самое, что файл `pairing_ws_device.json`.

Итого: **ничего отдельно «в браузере для device» делать не нужно** — достаточно тома `/workspace`, чтобы ключ не терялся между рестартами пода, и при необходимости один раз одобрить device в UI шлюза того же пода.

---

## Каталог «популярных» моделей

Редактируйте [`model_hub/catalog.json`](model_hub/catalog.json) в репозитории и пересоберите образ, либо монтируйте свой файл в `/opt/guildclaw/model_hub/catalog.json`.

---

## RTX 50 / sm_120

Образ собирается с `CMAKE_CUDA_ARCHITECTURES` без **120** (ограничения CUDA 12.4 в базе). Для нативного Blackwell пересоберите Dockerfile с архитектурой **120** и подходящей базой CUDA.

---

## Про `a2go-main`

Папка `a2go-main` при желании — отдельный апстрим; Guildclaw на неё не завязан.
