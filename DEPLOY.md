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
  -e MODEL_HUB_TOKEN="секрет-хаб" \
  -e HF_TOKEN="" \
  -p 8000:8000 -p 8080:8080 -p 8081:8081 -p 8888:8888 -p 18789:18789 \
  -v guildclaw_data:/workspace \
  youruser/guildclaw:latest
```

- **Model Hub:** `http://localhost:8080/?token=<MODEL_HUB_TOKEN>` (если токен задан; иначе без query). Токен Hub и опционально HF можно **сохранить в браузере** (блок «Токены» или страница входа при 401) — как в Control UI, без вечного `?token=` в закладке. Интерфейс: вкладки **Пресеты**, **HuggingFace**, **Мои GGUF** (активация / удаление).
- **Pairing dashboard (:8081):** только **node pairing** — то же хранилище, что и `openclaw nodes pending` / `node.pair.list`. Запись в очереди появляется только если мобильный (или другой) клиент к **WebSocket шлюза :18789** вызывает **`node.pair.request`** ([дока](https://openclaws.io/docs/gateway/pairing/)); вход в Control UI как **operator** сюда не попадает — это **`openclaw devices …`**. На RunPod нода должна целиться в **`wss://<pod-id>-18789.proxy.runpod.net`**, токен как у шлюза (**`OPENCLAW_WEB_PASSWORD`**). Дашборд внутри пода ходит на **`OPENCLAW_GATEWAY_WS`** (по умолчанию `ws://127.0.0.1:18789`). Секрет страницы: **`PAIRING_DASH_TOKEN`** или **`OPENCLAW_WEB_PASSWORD`**. Для RPC нужен Ed25519 device (**`pairing_ws_device.json`**), иначе «missing scope: operator.pairing».
- **OpenClaw UI:** `http://localhost:18789/?token=<OPENCLAW_WEB_PASSWORD>`
- **Canvas / A2UI** (те же **18789**, пути `/__openclaw__/canvas/`, `/__openclaw__/a2ui/`): для прямых запросов к этим URL **`?token=` в адресной строке обычно не подходит`** — нужен заголовок **`Authorization: Bearer <OPENCLAW_WEB_PASSWORD>`** или **`x-openclaw-token: …`**. Пример: `curl -sS -H "Authorization: Bearer <OPENCLAW_WEB_PASSWORD>" "http://127.0.0.1:18789/__openclaw__/canvas/"`.
- **LLM API:** `http://localhost:8000/v1`
- **JupyterLab:** `http://localhost:8888/lab` — при заданном токене: `…/lab?token=<секрет>`. Токен: **`JUPYTER_LAB_TOKEN`**, иначе подставляется **`ACCESS_PASSWORD`** (как в шаблоне ComfyUI/RunPod). Отключить: **`ENABLE_JUPYTER=0`**. Рабочая директория по умолчанию: **`/workspace`**. Лог: `/workspace/logs/jupyterlab.log`. В области агента: **`openclaw/OpenClaw_Быстрый_старт.ipynb`** (краткая инструкция по OpenClaw) и **`openclaw/Guildclaw_Mate.ipynb`** (проверки как у **`guildclaw-mate`** по ячейкам).

**Guildclaw Mate** (в контейнере): **`guildclaw-mate`** (после старта пода также **`/workspace/guildclaw-mate`** и запись в **`PATH`**). Если команда не находится: **`python3 /opt/guildclaw/scripts/guildclaw_mate.py doctor`**. У Python аргументы идут **после имени файла**: `python3 …/guildclaw_mate.py doctor`, а не `python3 doctor`. По умолчанию **`--cwd /workspace`**. Подкоманды: **`info`**, **`doctor`**, **`telegram`**, **`oc …`**. Без аргументов — **`info`**.

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
| 18789 | OpenClaw **gateway** (Web UI, WS, **Canvas / A2UI** по путям `/__openclaw__/canvas/` и `/__openclaw__/a2ui/` — см. [Canvas host](https://docs.openclaw.ai/gateway/configuration-reference#canvas-host)) |
| 18790 | **Legacy TCP Bridge** — в актуальных сборках OpenClaw **не поднимается** ([Bridge protocol](https://docs.openclaw.ai/gateway/bridge-protocol): «TCP bridge has been removed»). Прокси на **18790** часто даёт **502**. |
| 18793 | В **официальной** схеме OpenClaw отдельный порт Canvas **не описан**; в образе порт оставлен «на всякий случай», но процесс на нём **может не слушать** → **502**. Используйте **18789** + пути выше. |

### Переменные окружения

| Переменная | Описание |
| ---------- | -------- |
| `LLAMA_API_KEY` | Ключ для API llama-server (`Authorization: Bearer`) |
| `OPENCLAW_WEB_PASSWORD` | Токен Web UI OpenClaw |
| `MODEL_HUB_TOKEN` | **Рекомендуется:** токен для Model Hub (иначе UI/API без защиты) |
| `PAIRING_DASH_TOKEN` | Опционально: отдельный секрет для Pairing dashboard (`:8081`); если пусто — для доступа к дашборду используется `OPENCLAW_WEB_PASSWORD` |
| `ENABLE_JUPYTER` | `1` (по умолчанию): запускать JupyterLab на **8888**. `0` — не запускать |
| `JUPYTER_LAB_TOKEN` | Токен входа в JupyterLab (`?token=…`). Если пусто, используется **`ACCESS_PASSWORD`** (совместимость с шаблоном ComfyUI/RunPod). Если оба пусты — Lab без токена (**не рекомендуется** на публичном прокси) |
| `ACCESS_PASSWORD` | Опционально: общий пароль/токен для RunPod-шаблонов; при отсутствии `JUPYTER_LAB_TOKEN` подставляется в JupyterLab |
| `SERVED_MODEL_NAME` | Явный **alias** в API/OpenClaw; значение **`local-gguf`** (по умолчанию) значит *авто*: id строится из имени файла как `local-<slug>-gguf` (например `Qwen3.5-4B-Q8_0.gguf` → `local-qwen3-5-4b-q8-0-gguf`). Любой другой непустой текст — зафиксированный id |
| `LLAMA_CTX_SIZE` | Размер контекста для **llama-server** (`-c`) и поля `contextWindow` в OpenClaw (по умолчанию в образе **16384**). OpenClaw в логах предупреждает при **ctx меньше 32000**; для стабильного агента на RunPod часто ставят **32768**, если хватает VRAM. Значения **ниже 16000** поднимаются до **16000**. |
| `OPENCLAW_AGENT_MIN_CTX` | Нижняя граница для clamp (по умолчанию `16000`); менять только если апстрим OpenClaw изменит требование |
| `OPENCLAW_COMPACTION_RESERVE_TOKENS_FLOOR` | Целевой буфер компакции в `agents.*.compaction.reserveTokensFloor` (по умолчанию **20000**). Реальное значение **клампится** под `LLAMA_CTX_SIZE` и под **headroom** (см. ниже), иначе precheck даёт «prompt too large» / сброс чата при **16k**. |
| `OPENCLAW_COMPACTION_PROMPT_HEADROOM` | Минимум токенов, оставляемых под системный промпт, тулы и диалог (**по умолчанию 12000**). Резерв компакции не может съедать этот кусок окна; при необходимости поднимите **`LLAMA_CTX_SIZE`**. |
| `LLAMA_N_GPU_LAYERS` | Слоёв на GPU (99 ≈ максимум доступных) |
| `LLAMA_SERVER_EXTRA_ARGS` | Доп. флаги `llama-server` (строка) |
| `HF_TOKEN` | Для загрузок с Hugging Face (gated / лимиты) |
| `BOOTSTRAP_GGUF` | `1` (по умолчанию): если нет валидного `active.json`, скачать дефолтный GGUF и активировать. `0` — только Hub вручную |
| `DEFAULT_GGUF_URL` | URL дефолтного `.gguf` (по умолчанию **unsloth/Qwen3.5-4B-GGUF** `Qwen3.5-4B-Q8_0.gguf` на HF) |
| `DEFAULT_GGUF_FILENAME` | Имя файла в `/workspace/models/gguf/` (по умолчанию `Qwen3.5-4B-Q8_0.gguf`) |
| `OPENCLAW_STATE_DIR` | По умолчанию в контейнере с **`/workspace`**: **`/workspace/.openclaw`** (реальный каталог на томе). Раньше дефолт был `~/.openclaw` → symlink, из‑за чего OpenClaw мог отклонять **exec** (`Refusing to traverse symlink in exec approvals path`). Явно задайте переменную, только если нужен другой путь. |
| `TELEGRAM_BOT_TOKEN` | Токен бота от [@BotFather](https://t.me/BotFather). Можно **не** задавать при создании пода: добавьте переменную в RunPod (**Edit pod → Environment** или шаблон), **перезапустите под** — при старте токен **допишется** в `channels.telegram` внутри `$OPENCLAW_STATE_DIR/openclaw.json` (обычно `/workspace/.openclaw/`). Вручную: тот же файл, ключ `channels.telegram.botToken`, `enabled: true`. Если в конфиге у `telegram` стоит `"enabled": false`, автозапись токена пропускается (чтобы не включать канал против воли); форс: **`TELEGRAM_FORCE=1`**. |
| `WEB_SEARCH` | `1` / `true` / `yes` / `on` — при каждом старте пода в `openclaw.json` выставляется **`tools.web.search.provider`: `duckduckgo`** ([дока OpenClaw](https://docs.openclaw.ai/tools/duckduckgo-search)). Пусто — не трогаем секцию `tools` (можно задать провайдер вручную). |
| `WEB_SEARCH_PROVIDER` | Явное имя провайдера (`duckduckgo`, `searxng`, …), если нужно не короткое `WEB_SEARCH=1`. Если задано непустое значение, оно **перекрывает** автоматический выбор из `WEB_SEARCH`. |
| `OPENCLAW_CONTROL_UI_ALLOWED_ORIGINS` | Доп. origin для Control UI (через запятую), если заходите не с RunPod-прокси |
| `OPENCLAW_CONTROL_UI_ALLOW_ANY` | `1` / `true` — `allowedOrigins: ["*"]` (проще, но слабее с точки зрения безопасности) |
| `RUNTIME_STATE_DIR` | Каталог состояния стека (`active.json`, `pairing_ws_device.json`); по умолчанию **`/workspace/.guildclaw`**. |
| `MODEL_GGUF_DIR` | Каталог файлов **.gguf**; по умолчанию **`/workspace/models/gguf`**. |
| `PAIRING_DEVICE_JSON` | Полный путь к JSON с Ed25519-ключом дашборда pairing (иначе **`$RUNTIME_STATE_DIR/pairing_ws_device.json`**). |
| `OPENCLAW_LLAMA_SYNC_SCRIPT` | Путь к **`sync_openclaw_llama.py`** при нестандартной раскладке образа. |
| `LLAMA_PID_FILE` | Путь к pid-файлу **llama-server** (по умолчанию **`/tmp/guildclaw-llama.pid`**). |
| `MATE_CWD` | Рабочая директория по умолчанию для **`guildclaw-mate`** (иначе **`/workspace`**). |

**Устаревшие имена** (в entrypoint и Python по-прежнему читаются как fallback): `GUILDCLAW_HUB_TOKEN`, `GUILDCLAW_PAIRING_DASH_TOKEN`, `GUILDCLAW_JUPYTER`, `GUILDCLAW_JUPYTER_TOKEN`, `GUILDCLAW_WEB_SEARCH`, `GUILDCLAW_WEB_SEARCH_PROVIDER`, `GUILDCLAW_BOOTSTRAP_GGUF`, `GUILDCLAW_DEFAULT_GGUF_URL`, `GUILDCLAW_DEFAULT_GGUF_FILENAME`, `GUILDCLAW_TELEGRAM_FORCE`, `GUILDCLAW_STATE_DIR`, `GUILDCLAW_GGUF_DIR`, `GUILDCLAW_LLAMA_PID_FILE`, `GUILDCLAW_SYNC_SCRIPT`, `GUILDCLAW_PAIRING_DEVICE_JSON`, `GUILDCLAW_MATE_CWD`.

Переменная **`RUNPOD_POD_ID`** задаётся RunPod сама; в `openclaw.json` автоматически добавляется `https://<pod>-18789.proxy.runpod.net` в `gateway.controlUi.allowedOrigins` перед стартом шлюза.

Совместимость: если в образе **`LLAMA_API_KEY=changeme`**, а вы задали только **`VLLM_API_KEY`** (как в старых шаблонах), он **подставится** и в llama-server, и в `openclaw.json` после синка. Явно задайте **`LLAMA_API_KEY`**, если нужен отдельный ключ только для LLM API.

### URL на RunPod

- Hub: `https://<pod-id>-8080.proxy.runpod.net/?token=<MODEL_HUB_TOKEN>`
- Pairing: `https://<pod-id>-8081.proxy.runpod.net/?token=<PAIRING_DASH_TOKEN_или_OPENCLAW_WEB_PASSWORD>`
- JupyterLab: `https://<pod-id>-8888.proxy.runpod.net/lab?token=<JUPYTER_LAB_TOKEN_или_ACCESS_PASSWORD>`
- OpenClaw (шлюз + UI): `https://<pod-id>-18789.proxy.runpod.net/?token=<OPENCLAW_WEB_PASSWORD>`
- Canvas / A2UI (под шлюзом): база `https://<pod-id>-18789.proxy.runpod.net/__openclaw__/canvas/` и `…/a2ui/`. Для **GET в браузере** `?token=…` **часто не принимается** — шлюз ждёт **`Authorization: Bearer <OPENCLAW_WEB_PASSWORD>`** или **`x-openclaw-token: …`**. Пример: `curl -sS -H "Authorization: Bearer <OPENCLAW_WEB_PASSWORD>" "https://<pod-id>-18789.proxy.runpod.net/__openclaw__/canvas/"`.

**Про 18790 / 18793 и 502:** в текущем OpenClaw **отдельный TCP Bridge на 18790 снят**, а **Canvas** в доке идёт **через порт шлюза 18789**, не через отдельный «Canvas-only» порт ([configuration reference — Canvas host](https://docs.openclaw.ai/gateway/configuration-reference#canvas-host)). Поэтому **Cloudflare 502** на `…-18790…` и `…-18793…` — это не «сломался Guildclaw», а **на этих портах часто просто нет HTTP-сервиса**.

Откройте в RunPod порты, которыми реально пользуетесь: минимум **18789**, **8080**, **8000**, **8081**, **8888**. **18790 / 18793** в списке RunPod не обязательны; их можно убрать, если не хотите путаться с «мёртвыми» прокси.

### Pod, браузер и «device» для Pairing dashboard

Здесь две разные вещи, их не путайте:

1. **Ваш браузер** — вы только открываете **HTTPS на порт 8081** (страница со списком и кнопками). Это обычный HTTP; токен в URL / Bearer защищает именно **дашборд**, а не WebSocket шлюза OpenClaw. Браузер **не** подключается к `wss://…18789` и **не** является тем «device», о котором говорит протокол шлюза.

2. **Device для WS** — это **процесс Pairing dashboard внутри пода**: он сам ходит на **`ws://127.0.0.1:18789`**, держит ключ Ed25519 в файле **`/workspace/.guildclaw/pairing_ws_device.json`** (на том же томе, что и модели, если вы монтируете `/workspace`). После первого успешного запуска ключ **сохраняется**; пересоздавать его из браузера не нужно. Путь можно переопределить: **`PAIRING_DEVICE_JSON`**.

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
