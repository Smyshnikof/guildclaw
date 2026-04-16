# Guildclaw — RunPod Template

**Guildclaw** — один Docker-образ: **OpenClaw** (шлюз, агент, Web UI), **llama-server** (llama.cpp, GGUF, OpenAI-совместимый API), **Model Hub** (скачивание и активация `.gguf`), опционально **JupyterLab** и **Pairing dashboard**. Данные и модели живут на томе **`/workspace`**.

> При желании сюда можно вставить ссылку на плейлист / ролики по развёртыванию (как в шаблонах Wan и т.п.).

**Репозиторий:** [github.com/Smyshnikof/guildclaw](https://github.com/Smyshnikof/guildclaw) · полная документация: **[DEPLOY.md](DEPLOY.md)** · образ по умолчанию: **`smyshnikof/guildclaw:latest`**.

---

## Открытые порты

В RunPod в настройках пода откройте нужные порты как **HTTP** (или TCP для SSH). Если прокси **8081** / **8888** не открываются — явно добавьте их в список портов пода.

| Порт  | Тип  | Сервис |
| ----- | ---- | ------ |
| 22    | TCP  | SSH |
| 8000  | HTTP | **llama-server** — локальный LLM API (`/v1`, Bearer = `LLAMA_API_KEY`) |
| 8080  | HTTP | **Model Hub** — пресеты Hugging Face, своя ссылка на `.gguf`, активация / удаление модели |
| 8081  | HTTP | **Pairing dashboard** — очередь **node pairing** (удалённые ноды к шлюзу `:18789`) |
| 8888  | HTTP | **JupyterLab** — ноутбуки и терминал в `/workspace` |
| 18789 | HTTP | **OpenClaw Gateway** + Web UI; **Canvas / A2UI** — те же **18789**, пути `/__openclaw__/canvas/` и `/__openclaw__/a2ui/` ([дока](https://docs.openclaw.ai/gateway/configuration-reference#canvas-host)) |
| 18790 | — | **Legacy Bridge** — в актуальном OpenClaw TCP-слушатель **не поднимается** ([Bridge protocol](https://docs.openclaw.ai/gateway/bridge-protocol)); прокси часто даёт **502**. |
| 18793 | — | Отдельный Canvas-порт в upstream **не задокументирован**; на нём может **не быть** процесса → **502**. |

**Типичные URL на RunPod** (подставьте `<pod-id>`):

| Сервис | URL |
| ------ | --- |
| Model Hub | `https://<pod-id>-8080.proxy.runpod.net/?token=<MODEL_HUB_TOKEN>` |
| Pairing | `https://<pod-id>-8081.proxy.runpod.net/?token=<PAIRING_DASH_TOKEN>` или тот же токен, что у Web UI |
| JupyterLab | `https://<pod-id>-8888.proxy.runpod.net/lab?token=<токен>` |
| OpenClaw | `https://<pod-id>-18789.proxy.runpod.net/?token=<OPENCLAW_WEB_PASSWORD>` |
| Canvas (HTTP) | `https://<pod-id>-18789.proxy.runpod.net/__openclaw__/canvas/?token=<OPENCLAW_WEB_PASSWORD>` |
| A2UI | `https://<pod-id>-18789.proxy.runpod.net/__openclaw__/a2ui/?token=<OPENCLAW_WEB_PASSWORD>` |

**Не ждите ответа на `…-18790…` / `…-18793…`:** см. таблицу портов выше.

---

## Том и диск

| Параметр | Рекомендация |
| -------- | ------------ |
| Монтирование | Том на **`/workspace`** (модели GGUF, `.openclaw`, логи) |
| `containerDiskInGb` | **50+** GB в шаблоне, если планируете несколько крупных GGUF |

---

## Переменные окружения (шаблон)

Ниже — переменные из **`runpod-template.json`** и зачем они. Пустые значения в шаблоне задайте в UI RunPod при создании пода.

| Переменная | Обязательно | За что отвечает |
| ---------- | ----------- | ---------------- |
| `LLAMA_API_KEY` | **Да** | Секрет для запросов к API на **:8000** (`Authorization: Bearer`). Совместимость: можно задать **`VLLM_API_KEY`** — подхватится как ключ LLM. |
| `OPENCLAW_WEB_PASSWORD` | **Да** | Токен входа в **OpenClaw Web UI** (:18789) и дефолтный доступ к Pairing dashboard, если отдельный токен не задан. |
| `MODEL_HUB_TOKEN` | Желательно | Защита **Model Hub** (:8080). Без токена UI открыт всем, кто знает URL. |
| `PAIRING_DASH_TOKEN` | Нет | Отдельный секрет только для страницы **:8081**; если пусто — используется `OPENCLAW_WEB_PASSWORD`. |
| `ENABLE_JUPYTER` | Нет | `1` — запускать JupyterLab на **8888**; `0` — не запускать. |
| `JUPYTER_LAB_TOKEN` | Желательно | Токен `?token=` для JupyterLab. Если пусто — берётся **`ACCESS_PASSWORD`**. |
| `ACCESS_PASSWORD` | Нет | Удобно для шаблонов RunPod: один пароль на Jupyter, если не задан `JUPYTER_LAB_TOKEN`. |
| `SERVED_MODEL_NAME` | Нет | Алиас модели в OpenClaw/API. **`local-gguf`** = авто-id из имени файла после активации в Hub. |
| `LLAMA_CTX_SIZE` | Нет | Размер контекста **llama-server** (`-c`) и **`contextWindow`** в OpenClaw. Часто **32768**, если хватает VRAM; не больше, чем реально держит выбранный GGUF. |
| `LLAMA_N_GPU_LAYERS` | Нет | Слоёв на GPU (**99** ≈ все на GPU). |
| `OPENCLAW_COMPACTION_RESERVE_TOKENS_FLOOR` | Нет | Буфер компакции чата OpenClaw (цель **20000**; при малом `LLAMA_CTX_SIZE` образ **клампит** значение). |
| `OPENCLAW_COMPACTION_PROMPT_HEADROOM` | Нет | Запас под системный промпт и тулы (**12000** по умолчанию). |
| `HF_TOKEN` | Нет | Токен Hugging Face для gated-моделей и лимитов при скачивании из Hub. |
| `TELEGRAM_BOT_TOKEN` | Нет | При старте пода дописывается в `openclaw.json` → канал Telegram. Можно добавить позже и перезапустить под. |
| `WEB_SEARCH` | Нет | `1` / `true` / `True` — включить **`duckduckgo`** как провайдер `web_search` в конфиге OpenClaw при старте. |

**Дополнительно (не в minimal JSON шаблона, см. [DEPLOY.md](DEPLOY.md)):**  
`WEB_SEARCH_PROVIDER`, `HF_TOKEN`-связанные URL дефолтной модели, `BOOTSTRAP_GGUF`, `LLAMA_SERVER_EXTRA_ARGS`, `OPENCLAW_STATE_DIR`, `OPENCLAW_CONTROL_UI_*`, `TELEGRAM_FORCE` и др. Старые имена с префиксом **`GUILDCLAW_*`** в образе по-прежнему подхватываются как fallback.

---

## Быстрый старт

1. Задать **`LLAMA_API_KEY`**, **`OPENCLAW_WEB_PASSWORD`**, **`MODEL_HUB_TOKEN`**.
2. Открыть **Model Hub** (`…-8080…`) → скачать пресет или вставить URL на `.gguf` → **Активировать** → дождаться перезапуска **llama-server**.
3. Открыть **OpenClaw** (`…-18789…`) с токеном из `OPENCLAW_WEB_PASSWORD`.

Конфиг OpenClaw на томе: **`/workspace/.openclaw/openclaw.json`**. Проверки: в контейнере **`guildclaw-mate doctor`**.

---

## Про `LLAMA_CTX_SIZE` и «как на a2go.run»

Подбор контекста зависит от **конкретного GGUF и видеокарты**: в интерфейсах вроде [a2go.run](https://a2go.run/?agent=openclaw) или в карточке квантизации смотрят **рекомендуемый / типичный ctx** для модели.

- **`LLAMA_CTX_SIZE` в Guildclaw** — это то, с чем реально поднимется **llama-server** и что увидит OpenClaw. Ставить **можно не «любое число»**: если указать **больше**, чем модель и VRAM вытянут, будут OOM, деградация или обрезка на стороне сервера — ориентируйтесь на **фактический лимит кванта** и VRAM.
- Если на калькуляторе для слоя написано **66k** или **13k** — это **подсказка под железо и квант**, а не обязательность совпадения с одной цифрой в env: часто берут **стандартные ступени** (8192, 16384, 32768, …) **не выше** того, что стабильно держит ваш GGUF на GPU.
- **OpenClaw** дополнительно требует минимум окна для агента (в образе кламп не ниже **16000**); при малом окне срабатывают предупреждения и компакция — см. **DEPLOY.md**.

---

## Файл шаблона в репозитории

JSON для импорта в RunPod: **[runpod-template.json](runpod-template.json)** (`imageName`, `env`, `containerDiskInGb`).
