from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import hashlib
import os
import subprocess
import threading
import uuid

# Глобальный словарь для отслеживания статуса загрузок
download_status = {}


def _download_dest_dir(_folder: str) -> str:
    """Guildclaw: все файлы — в каталог GGUF (подпапки ComfyUI не используем)."""
    d = os.environ.get("GUILDCLAW_GGUF_DIR", "/workspace/models/gguf")
    os.makedirs(d, exist_ok=True)
    return d
import requests
import json
from huggingface_hub import hf_hub_download, login
import tempfile

app = FastAPI(title="Guildclaw Model Hub")

# Статика (script.js и др.)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ComfyUI / Wan / Qwen / … пресеты удалены — только model_hub/catalog.json.
PRESET_FILES: dict[str, list] = {}

PRESET_CATEGORIES: dict[str, dict] = {}

PRESETS: dict[str, dict] = {}


def _merge_guildclaw_catalog() -> None:
    """Добавляет пресеты из model_hub/catalog.json (GGUF для llama-server)."""
    catalog_path = os.path.join(os.path.dirname(__file__), "catalog.json")
    if not os.path.isfile(catalog_path):
        return
    with open(catalog_path, encoding="utf-8") as f:
        data = json.load(f)
    for m in data.get("models", []):
        pid = m.get("id")
        url = (m.get("url") or "").strip()
        if not pid or not url or pid in PRESET_FILES:
            continue
        fn = url.split("/")[-1].split("?")[0]
        PRESET_FILES[pid] = [(url, "gguf", fn)]
        cat_name = str(m.get("category", "Guildclaw"))
        cat_slug = "GC_" + hashlib.md5(cat_name.encode("utf-8")).hexdigest()[:10]
        if cat_slug not in PRESET_CATEGORIES:
            PRESET_CATEGORIES[cat_slug] = {"name": cat_name, "icon": "🦞", "color": "#22c55e"}
        gb = m.get("approx_gb", "?")
        PRESETS[pid] = {
            "name": m.get("label", pid),
            "description": m.get("description", ""),
            "size": f"~{gb} GB" if gb != "?" else "?",
            "time": "—",
            "category": cat_slug,
        }


_merge_guildclaw_catalog()

INDEX_HTML = """
<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Guildclaw Hub · preset+script</title>
  <style>
    :root { --bg:#1e1e1e; --card:#282828; --text:#ffffff; --muted:#9ca3af; --accent:#ffffff; --accent-border:#000000; }
    html,body { margin:0; padding:0; background:var(--bg); color:var(--text); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Arial; }
    .wrap { max-width: 1200px; margin: 0 auto; padding: 40px 20px; }
    .title { font-size: 36px; font-weight: 800; margin: 0 0 8px; color: var(--accent); text-align: center; text-shadow: 0 0 10px rgba(255,255,255,0.3); }
    .subtitle { margin:0 0 40px; color:var(--muted); text-align: center; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin: 0 auto; max-width: 1000px; }
    .card { background: var(--card); border:1px solid #3a3a3a; border-radius: 12px; padding: 24px; box-sizing: border-box; }
    .row { display:grid; grid-template-columns: 200px 1fr; gap:16px; align-items:center; margin:16px 0; }
    .row-full { display:grid; grid-template-columns: 1fr; gap:16px; margin:16px 0; }
    input[type=text], input[type=password] { width:100%; padding:12px 16px; background:#1a1a1a; border:1px solid #3a3a3a; color:var(--text); border-radius:8px; box-sizing: border-box; }
    .btn { display:inline-flex; align-items:center; gap:8px; padding:12px 20px; background: rgba(255,255,255,0.9); color:var(--bg); font-weight:700; border:2px solid rgba(255,255,255,0.5); border-radius:8px; cursor:pointer; transition: all 0.2s; }
    .btn:hover { background: var(--accent); color:var(--bg); border-color: var(--accent); }
    .btn:disabled { opacity:0.5; cursor:not-allowed; }
    .btn-preset { 
      background: rgba(34, 197, 94, 0.9); 
      color: white; 
      border-color: rgba(34, 197, 94, 0.5); 
      box-shadow: 0 4px 12px rgba(34, 197, 94, 0.3);
    }
    .btn-preset:hover { 
      background: rgb(34, 197, 94); 
      color: white;
      border-color: rgb(34, 197, 94); 
      box-shadow: 0 8px 20px rgba(34, 197, 94, 0.5);
    }
    .btn-hf { 
      background: rgba(255, 193, 7, 0.9); 
      color: black; 
      border-color: rgba(255, 193, 7, 0.5); 
      box-shadow: 0 4px 12px rgba(255, 193, 7, 0.3);
    }
    .btn-hf:hover { 
      background: rgb(255, 193, 7); 
      color: black;
      border-color: rgb(255, 193, 7); 
      box-shadow: 0 8px 20px rgba(255, 193, 7, 0.5);
    }
    a { color:var(--accent); text-decoration:none; border-bottom: 1px solid rgba(255,255,255,0.3); }
    a:hover { text-decoration:none; border-bottom-color: var(--accent); }
    .hint { background:#1a1a1a; border:1px dashed #3a3a3a; padding:16px; border-radius:8px; margin-bottom:20px; }
    .result { white-space: pre-wrap; background:#1a1a1a; border:1px solid #3a3a3a; padding:16px; border-radius:8px; margin-top:20px; min-height:24px; }
    .progress { margin-top:20px; }
    .progress-bar { width:100%; height:8px; background:#1a1a1a; border:1px solid #3a3a3a; border-radius:4px; overflow:hidden; }
    .progress-fill { height:100%; background:var(--accent); width:0%; transition:width 0.3s; }
    .progress-text { margin-top:8px; color:var(--muted); font-size:14px; text-align:center; }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace; }
    .preset-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 16px; margin: 20px 0; }
    .preset-card { background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; padding: 16px; cursor: pointer; transition: all 0.2s; position: relative; }
    .preset-card:hover { border-color: var(--accent); background: #222; }
    .preset-card.selected { border-color: var(--accent); background: rgba(255,255,255,0.1); }
    .preset-name { font-weight: 700; margin-bottom: 8px; color: var(--accent); }
    .preset-desc { color: var(--muted); font-size: 14px; margin-bottom: 8px; }
    .preset-info { font-size: 12px; color: var(--muted); }
    .video-guide-icon { 
      position: absolute;
      top: 12px;
      right: 12px;
      width: 22px; 
      height: 22px; 
      background: white; 
      border-radius: 50%; 
      display: inline-flex; 
      align-items: center; 
      justify-content: center; 
      color: black; 
      font-weight: bold; 
      font-size: 14px; 
      text-decoration: none; 
      transition: all 0.2s;
      border: 1px solid rgba(255,255,255,0.3);
      z-index: 10;
    }
    .video-guide-icon:hover { 
      background: var(--accent); 
      color: var(--bg); 
      transform: scale(1.15);
      box-shadow: 0 0 10px rgba(255,255,255,0.4);
    }
    .tabs { display: flex; gap: 8px; margin-bottom: 20px; justify-content: center; flex-wrap: wrap; }
    .tab { padding: 8px 16px; background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; cursor: pointer; transition: all 0.2s; }
    .tab.active { background: var(--accent); color: var(--bg); }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
    .search-container { margin-bottom: 20px; position: relative; }
    .search-input { width: 100%; padding: 12px 16px 12px 44px; background: #1a1a1a; border: 1px solid #3a3a3a; color: var(--text); border-radius: 8px; box-sizing: border-box; font-size: 14px; }
    .search-icon { position: absolute; left: 14px; top: 50%; transform: translateY(-50%); color: var(--muted); pointer-events: none; }
    .category-filters { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; align-items: center; }
    .category-filter { padding: 8px 16px; background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; gap: 6px; font-size: 14px; }
    .category-filter:hover { border-color: var(--accent); background: #222; }
    .category-filter.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }
    .category-filter.all { background: #2a2a2a; }
    .category-filter.all.active { background: var(--accent); }
    .preset-card.hidden { display: none; }
    .preset-variants { margin-top: 12px; padding-top: 12px; border-top: 1px solid #3a3a3a; display: none; }
    .preset-card.expanded .preset-variants { display: block; }
    .preset-variant-group { margin-bottom: 16px; }
    .preset-variant-group-title { font-size: 13px; font-weight: 600; color: var(--accent); margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #2a2a2a; }
    .preset-variant-item { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; padding: 8px; background: #0f0f0f; border-radius: 6px; cursor: pointer; transition: all 0.2s; }
    .preset-variant-item:hover { background: #151515; }
    .preset-variant-item input[type="checkbox"] { width: 16px; height: 16px; cursor: pointer; }
    .preset-variant-label { flex: 1; font-size: 13px; color: var(--muted); }
    .preset-variant-label strong { color: var(--text); }
    .preset-variant-info { font-size: 11px; color: var(--muted); }
    .preset-expand-icon { position: absolute; top: 50%; right: 16px; transform: translateY(-50%); font-size: 18px; color: var(--muted); transition: transform 0.2s; cursor: pointer; z-index: 5; }
    .preset-card.expanded .preset-expand-icon { transform: translateY(-50%) rotate(180deg); }
    .preset-expand-icon:hover { color: var(--accent); }
  </style>
</head>
<body>
  <!-- hub-ui:preset-downloader (не старый UI v2; вкладки с 🎯 🤗 🦞) -->
  <div class="wrap">
    <h1 class="title">Guildclaw Model Hub</h1>
    <p class="subtitle">Пресеты только из <span class="mono">model_hub/catalog.json</span> · HuggingFace · активация llama-server / OpenClaw</p>
    
    <div class="tabs">
      <div class="tab active" onclick="switchTab('presets')">🎯 Пресеты</div>
      <div class="tab" onclick="switchTab('huggingface')">🤗 HuggingFace</div>
      <div class="tab" onclick="switchTab('guildclaw')">🦞 Мои GGUF</div>
    </div>
    
    <div class="grid">
      <!-- Пресеты -->
      <div class="card tab-content active" id="presets-tab">
        <h3>GGUF-пресеты из catalog.json</h3>
        
        <!-- Поиск -->
        <div class="search-container">
          <input type="text" class="search-input" id="preset-search" placeholder="Поиск пресетов..." oninput="filterPresets()">
        </div>
        
        <!-- Фильтры категорий -->
        <div class="category-filters" id="category-filters">
          {{ category_filters_html }}
        </div>
        
        <div class="preset-grid" id="preset-grid">
          {{ presets_html }}
        </div>
        <div class="row-full">
          <button class="btn btn-preset" onclick="downloadPresets()" id="download-presets-btn" disabled>
            📥 Скачать выбранные пресеты
          </button>
        </div>
        <div class="result" id="preset-result"></div>
        <div class="progress" id="preset-progress" style="display:none;">
          <div class="progress-bar">
            <div class="progress-fill" id="preset-progress-fill"></div>
          </div>
          <div class="progress-text" id="preset-progress-text">Загрузка...</div>
        </div>
      </div>
      
      <!-- HuggingFace -->
      <div class="card tab-content" id="huggingface-tab">
        <div class="hint">
          <b>Как использовать?</b> Выберите способ: прямая ссылка на файл (рекомендуется) или HuggingFace репозиторий. 
          Для приватных моделей нужен API токен с правами "Read" - см. инструкцию ниже.
        </div>
        
        <div class="tabs" style="margin-bottom: 20px;">
          <div class="tab active" onclick="switchHFMethod('url')">🔗 Прямая ссылка</div>
          <div class="tab" onclick="switchHFMethod('repo')">🤗 HuggingFace Repo</div>
        </div>
        
        <!-- Прямая ссылка метод (дефолтный) -->
        <form id="hf-url-form" method="post" action="/download_url" style="margin-top:12px;">
          <div class="row">
            <label for="hf_url">Прямая ссылка на файл</label>
            <input id="hf_url" type="text" name="url" placeholder="https://huggingface.co/…/resolve/main/model-Q4_K_M.gguf" required />
          </div>
          <div class="row">
            <label for="hf_url_folder">Куда кладём</label>
            <select id="hf_url_folder" name="folder" style="width:100%; padding:12px 16px; background:#1a1a1a; border:1px solid #3a3a3a; color:var(--text); border-radius:8px;">
              <option value="gguf" selected>Каталог GGUF (GUILDCLAW_GGUF_DIR)</option>
            </select>
          </div>
          <div class="row" style="grid-template-columns:1fr;">
            <button class="btn btn-hf" type="submit">🔗 Скачать по ссылке</button>
          </div>
        </form>
        
        <!-- HuggingFace Repo метод -->
        <form id="hf-repo-form" method="post" action="/download_hf" style="margin-top:12px; display:none;">
          <div class="row">
            <label for="hf_repo">Репозиторий</label>
            <input id="hf_repo" type="text" name="repo" placeholder="username/model-name" value="{{ hf_repo_value }}" />
          </div>
          <div class="row">
            <label for="hf_file">Файл (опционально)</label>
            <input id="hf_file" type="text" name="filename" placeholder="model-Q4_K_M.gguf" value="{{ hf_file_value }}" />
          </div>
          <div class="row">
            <label for="hf_token">API токен (опционально)</label>
            <input id="hf_token" type="password" name="token" placeholder="hf_..." value="{{ hf_token_value }}" autocomplete="current-password" />
            <div style="margin-top: 8px; padding: 12px; background: #1a1a1a; border: 1px solid #3a3a3a; border-radius: 8px; font-size: 12px; word-wrap: break-word;">
              <div style="color: #4a9eff; font-weight: 600; margin-bottom: 8px;">📋 Как создать токен:</div>
              <div style="color: #ccc; line-height: 1.4;">
                1. Перейдите по ссылке: <a href="https://huggingface.co/settings/tokens" target="_blank" style="color: #4a9eff; text-decoration: underline;">https://huggingface.co/settings/tokens</a><br>
                2. Нажмите "New token"<br>
                3. Выберите "Read" (достаточно для скачивания)<br>
                4. Введите название токена<br>
                5. Нажмите "Create token"<br>
                6. Скопируйте токен (начинается с hf_...)
              </div>
            </div>
          </div>
          <div class="row">
            <label for="hf_folder">Куда кладём</label>
            <select id="hf_folder" name="folder" style="width:100%; padding:12px 16px; background:#1a1a1a; border:1px solid #3a3a3a; color:var(--text); border-radius:8px;">
              <option value="gguf" selected>Каталог GGUF (GUILDCLAW_GGUF_DIR)</option>
            </select>
          </div>
          <div class="row" style="grid-template-columns:1fr;">
            <button class="btn btn-hf" type="submit">🤗 Скачать с HuggingFace</button>
          </div>
        </form>
        <div class="result" id="hf-result">{{ hf_result }}</div>
        <div class="progress" id="hf-progress" style="display:none;">
          <div class="progress-bar">
            <div class="progress-fill" id="hf-progress-fill"></div>
          </div>
          <div class="progress-text" id="hf-progress-text">Загрузка...</div>
        </div>
      </div>
      
      <div class="card tab-content" id="guildclaw-tab">
        <h3>Установленные .gguf</h3>
        <p style="color:var(--muted);font-size:14px;text-align:left;">Активная модель — для llama-server; OpenClaw: провайдер <code>local-llama</code>.</p>
        <button type="button" class="btn btn-preset" onclick="refreshGgufList()">Обновить список</button>
        <div id="gc-gguf-list" style="margin-top:12px;">Откройте вкладку — загрузка списка…</div>
      </div>
    </div>
  </div>
  
  <script src="/static/script.js"></script>
  <script>
    // Дополнительный JavaScript код для HuggingFace функций
    
    // Ждём полной загрузки DOM перед регистрацией обработчиков
    document.addEventListener('DOMContentLoaded', function() {
      console.log('HF handlers initializing...');
      
      // Проверяем наличие форм
      const hfForm = document.querySelector('form[action="/download_hf"]');
      const urlForm = document.querySelector('form[action="/download_url"]');
      
      if (!hfForm || !urlForm) {
        console.error('Forms not found!', { hfForm, urlForm });
        return;
      }
      
      console.log('Forms found, attaching handlers');
      
      // Обработка формы HuggingFace (только для репозитория)
      hfForm.addEventListener('submit', function(e) {
        e.preventDefault(); // Предотвращаем стандартную отправку формы
        console.log('HF form submitted');
        
        const progress = document.getElementById('hf-progress');
        const result = document.getElementById('hf-result');
        const btn = document.querySelector('form[action="/download_hf"] button[type="submit"]');
        
        // Показываем прогресс
        progress.style.display = 'block';
        result.textContent = '';
        btn.disabled = true;
        btn.textContent = 'Загрузка...';
        
        // Отправляем форму через fetch
        const formData = new FormData(this);
        
        fetch('/download_hf', gcFetchInit({
          method: 'POST',
          body: formData
        }))
        .then(response => response.json())
        .then(data => {
          if (data.task_id) {
            result.textContent = data.message;
            // Начинаем опрос статуса
            pollHFStatus(data.task_id);
          } else {
            result.textContent = data.message;
            progress.style.display = 'none';
            btn.disabled = false;
            btn.textContent = '🤗 Скачать с HuggingFace';
          }
        })
        .catch(error => {
          result.textContent = '❌ Ошибка: ' + error.message;
          progress.style.display = 'none';
          btn.disabled = false;
          btn.textContent = '🤗 Скачать с HuggingFace';
        });
      });
      
      // Обработка формы прямой ссылки
      urlForm.addEventListener('submit', function(e) {
        e.preventDefault(); // Предотвращаем стандартную отправку формы
        console.log('URL form submitted');
        
        const progress = document.getElementById('hf-progress');
        const result = document.getElementById('hf-result');
        const btn = document.querySelector('form[action="/download_url"] button[type="submit"]');
        
        // Показываем прогресс
        progress.style.display = 'block';
        result.textContent = '';
        btn.disabled = true;
        btn.textContent = 'Загрузка...';
        
        // Отправляем форму через fetch
        const formData = new FormData(this);
        
        fetch('/download_url', gcFetchInit({
          method: 'POST',
          body: formData
        }))
        .then(response => response.json())
        .then(data => {
          if (data.task_id) {
            result.textContent = data.message;
            // Начинаем опрос статуса
            pollHFStatus(data.task_id);
          } else {
            result.textContent = data.message;
            progress.style.display = 'none';
            btn.disabled = false;
            btn.textContent = '🔗 Скачать по ссылке';
          }
        })
        .catch(error => {
          result.textContent = '❌ Ошибка: ' + error.message;
          progress.style.display = 'none';
          btn.disabled = false;
          btn.textContent = '🔗 Скачать по ссылке';
        });
      });
      
      console.log('HF handlers attached successfully');
    });
    
    function pollHFStatus(taskId) {
      const progress = document.getElementById('hf-progress');
      const progressFill = document.getElementById('hf-progress-fill');
      const progressText = document.getElementById('hf-progress-text');
      const result = document.getElementById('hf-result');
      
      // Находим активную кнопку (видимую форму)
      const hfForm = document.getElementById('hf-repo-form');
      const urlForm = document.getElementById('hf-url-form');
      let btn = null;
      
      if (hfForm.style.display !== 'none') {
        btn = hfForm.querySelector('button[type="submit"]');
      } else if (urlForm.style.display !== 'none') {
        btn = urlForm.querySelector('button[type="submit"]');
      }
      
      if (!btn) {
        // Fallback - ищем любую кнопку
        btn = document.querySelector('form[action="/download_hf"] button[type="submit"]') || 
              document.querySelector('form[action="/download_url"] button[type="submit"]');
      }
      
      fetch('/status/' + taskId, gcFetchInit())
      .then(response => response.json())
      .then(data => {
        if (data.status === 'completed' || data.status === 'error') {
          result.textContent = data.message;
          progress.style.display = 'none';
          if (btn) {
            btn.disabled = false;
            btn.textContent = btn.textContent.includes('HuggingFace') ? '🤗 Скачать с HuggingFace' : '🔗 Скачать по ссылке';
          }
        } else if (data.status === 'running') {
          // Обновляем прогресс-бар
          const progressPercent = data.progress || 0;
          progressFill.style.width = progressPercent + '%';
          progressText.textContent = data.message || 'Загрузка...';
          result.textContent = data.message || 'Загрузка...';
          
          // Повторяем через 500ms для более плавного обновления
          setTimeout(() => pollHFStatus(taskId), 500);
        } else {
          result.textContent = '❌ Неизвестный статус: ' + data.message;
          progress.style.display = 'none';
          if (btn) {
            btn.disabled = false;
            btn.textContent = btn.textContent.includes('HuggingFace') ? '🤗 Скачать с HuggingFace' : '🔗 Скачать по ссылке';
          }
        }
      })
      .catch(error => {
        result.textContent = '❌ Ошибка проверки статуса: ' + error.message;
        progress.style.display = 'none';
        if (btn) {
          btn.disabled = false;
          btn.textContent = btn.textContent.includes('HuggingFace') ? '🤗 Скачать с HuggingFace' : '🔗 Скачать по ссылке';
        }
      });
    }
  </script>
</body>
</html>
"""

def generate_category_filters_html():
    html = '<div class="category-filter all active" onclick="filterByCategory(\'all\', event)">Все</div>'
    for category_id, category_info in PRESET_CATEGORIES.items():
        html += f'''
        <div class="category-filter" onclick="filterByCategory('{category_id}', event)" data-category="{category_id}">
          <span>{category_info['icon']}</span>
          <span>{category_info['name']}</span>
        </div>
        '''
    return html

def generate_presets_html():
    html = ""
    for preset_id, preset_info in PRESETS.items():
        category = preset_info.get("category", "Guildclaw")
        video_guide_html = ""
        if preset_info.get('video_guide'):
            video_guide_html = f'<a href="{preset_info["video_guide"]}" target="_blank" rel="noopener noreferrer" class="video-guide-icon" onclick="event.stopPropagation();" title="Видео-гайд">i</a>'
        
        # Проверяем, есть ли варианты (для Qwen пресетов)
        if preset_info.get('has_variants') and preset_info.get('variant_groups'):
            variants_html = ""
            for group_name, variants in preset_info['variant_groups'].items():
                group_html = f'<div class="preset-variant-group-title">{group_name}</div>'
                for variant_id, variant_info in variants.items():
                    group_html += f'''
                    <div class="preset-variant-item" onclick="event.stopPropagation();">
                      <input type="checkbox" id="variant-{variant_id}" data-variant="{variant_id}" data-parent="{preset_id}" onchange="toggleVariant('{preset_id}', '{variant_id}')">
                      <label for="variant-{variant_id}" class="preset-variant-label">
                        <strong>{variant_info['name']}</strong>
                        <span class="preset-variant-info"> • {variant_info['size']} • {variant_info['time']}</span>
                      </label>
                    </div>
                    '''
                variants_html += f'<div class="preset-variant-group">{group_html}</div>'
            
            html += f'''
            <div class="preset-card" data-preset="{preset_id}" data-category="{category}" onclick="togglePresetCard('{preset_id}', event)">
              {video_guide_html}
              <span class="preset-expand-icon" onclick="event.stopPropagation(); togglePresetCard('{preset_id}', event)">▼</span>
              <div class="preset-name">{preset_info['name']}</div>
              <div class="preset-desc">{preset_info['description']}</div>
              <div class="preset-info">Размер: {preset_info['size']} • Время: {preset_info['time']}</div>
              <div class="preset-variants">
                <div style="font-size: 12px; color: var(--muted); margin-bottom: 12px;">Выберите версию и формат:</div>
                {variants_html}
              </div>
            </div>
            '''
        else:
            # Обычная карточка без вариантов (Wan пресеты)
            html += f'''
            <div class="preset-card" data-preset="{preset_id}" data-category="{category}" onclick="togglePreset('{preset_id}')">
              {video_guide_html}
              <div class="preset-name">{preset_info['name']}</div>
              <div class="preset-desc">{preset_info['description']}</div>
              <div class="preset-info">Размер: {preset_info['size']} • Время: {preset_info['time']}</div>
            </div>
            '''
    return html

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    from .guildclaw_glue import hub_index_gate

    blocked = hub_index_gate(request)
    if blocked:
        return blocked
    presets_html = generate_presets_html()
    category_filters_html = generate_category_filters_html()
    return HTMLResponse(INDEX_HTML.replace("{{ presets_html }}", presets_html)
                       .replace("{{ category_filters_html }}", category_filters_html)
                       .replace("{{ hf_repo_value }}", "")
                       .replace("{{ hf_file_value }}", "")
                       .replace("{{ hf_token_value }}", "")
                       .replace("{{ hf_result }}", ""))

@app.get("/health")
def health_check():
    return PlainTextResponse("ok", status_code=200)


@app.get("/status/{task_id}")
def get_status(task_id: str, request: Request):
    from .guildclaw_glue import check_hub_request

    check_hub_request(request)
    if task_id not in download_status:
        return {"status": "not_found", "message": "Задача не найдена"}
    
    return download_status[task_id]


@app.get("/api/tasks")
def get_all_tasks(request: Request):
    """Список задач скачивания (для дашборда)."""
    from .guildclaw_glue import check_hub_request

    check_hub_request(request)
    # Filter to show only active/recent tasks
    active_tasks = []
    for task_id, status in download_status.items():
        task_info = {
            "task_id": task_id,
            **status
        }
        active_tasks.append(task_info)
    
    # Sort by most recent (downloading first, then completed)
    def sort_key(t):
        s = t.get("status", "")
        if s == "downloading":
            return 0
        elif s == "completed":
            return 1
        elif s == "error":
            return 2
        return 3
    
    active_tasks.sort(key=sort_key)
    return {"tasks": active_tasks[:20]}  # Limit to 20 most recent


@app.post("/download_presets")
def download_presets(request: Request, presets: str = Form(...)):
    from .guildclaw_glue import check_hub_request

    check_hub_request(request)
    try:
        # Парсим строку пресетов
        presets_list = [p.strip() for p in presets.split(',') if p.strip()]
        
        if not presets_list:
            return {"message": "❌ Не выбрано ни одного пресета"}
        
        # Запускаем скрипт скачивания пресетов в фоне
        import threading
        import uuid
        
        # Создаем уникальный ID для отслеживания
        task_id = str(uuid.uuid4())
        
        def download_file_with_progress(url, dest_dir, custom_filename, current_file, total_files, task_id):
            """Скачивает файл с отслеживанием прогресса в реальном времени, как в LoRA загрузчике"""
            import re
            
            # Определяем имя файла
            if custom_filename:
                filename = custom_filename
            else:
                filename = os.path.basename(url)
                # Убираем параметры запроса
                if '?' in filename:
                    filename = filename.split('?')[0]
            
            filepath = os.path.join(dest_dir, filename)
            os.makedirs(dest_dir, exist_ok=True)
            
            # Проверяем, существует ли файл
            if os.path.isfile(filepath) and os.path.getsize(filepath) > 0:
                download_status[task_id] = {
                    "status": "running",
                    "message": f"⏭️ Пропущено (уже существует): {filename} ({current_file}/{total_files})",
                    "progress": (current_file / total_files * 100),
                    "total_files": total_files,
                    "current_file": current_file,
                    "current_filename": filename
                }
                return "SKIP", filename
            
            # Обновляем статус - начало скачивания
            download_status[task_id] = {
                "status": "running",
                "message": f"📥 Скачивание файла {current_file} из {total_files}: {filename} (0%)",
                "progress": ((current_file - 1) / total_files * 100),
                "total_files": total_files,
                "current_file": current_file,
                "current_filename": filename
            }
            
            try:
                # Скачиваем файл с отслеживанием прогресса
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                hf_env = os.environ.get("HF_TOKEN", "").strip()
                if hf_env and "huggingface.co" in url:
                    headers["Authorization"] = f"Bearer {hf_env}"
                response = requests.get(url, stream=True, headers=headers, timeout=300)
                response.raise_for_status()
                
                # Получаем размер файла
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                last_update = 0
                update_interval = 1024 * 1024 * 5  # Обновляем каждые 5MB
                
                # Скачиваем по частям и обновляем прогресс
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Обновляем прогресс каждые 5MB или если это последний chunk
                            if downloaded - last_update >= update_interval or (total_size > 0 and downloaded >= total_size):
                                last_update = downloaded
                                
                                # Обновляем прогресс
                                if total_size > 0:
                                    file_percent = int((downloaded / total_size) * 100)
                                    # Вычисляем общий прогресс: (current-1)/total + file_percent/(100*total)
                                    overall_progress = ((current_file - 1) / total_files * 100) + (file_percent / total_files)
                                    
                                    download_status[task_id] = {
                                        "status": "running",
                                        "message": f"📥 Скачивание файла {current_file} из {total_files}: {filename} ({file_percent}%)",
                                        "progress": min(overall_progress, 100),
                                        "total_files": total_files,
                                        "current_file": current_file,
                                        "current_filename": filename
                                    }
                                else:
                                    # Если размер неизвестен, показываем только что идет скачивание
                                    size_mb = downloaded / (1024 * 1024)
                                    download_status[task_id] = {
                                        "status": "running",
                                        "message": f"📥 Скачивание файла {current_file} из {total_files}: {filename} ({size_mb:.1f} MB)",
                                        "progress": ((current_file - 1) / total_files * 100) + 0.1,  # Минимальный прогресс
                                        "total_files": total_files,
                                        "current_file": current_file,
                                        "current_filename": filename
                                    }
                
                # Финальное обновление - файл скачан
                download_status[task_id] = {
                    "status": "running",
                    "message": f"✅ Завершено: {filename} ({current_file}/{total_files})",
                    "progress": (current_file / total_files * 100),
                    "total_files": total_files,
                    "current_file": current_file,
                    "current_filename": filename
                }
                
                return "DOWNLOADED", filename
                
            except Exception as e:
                # Удаляем частично скачанный файл
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                download_status[task_id] = {
                    "status": "running",
                    "message": f"❌ Ошибка скачивания: {filename} ({current_file}/{total_files}) - {str(e)[:100]}",
                    "progress": ((current_file - 1) / total_files * 100),
                    "total_files": total_files,
                    "current_file": current_file,
                    "current_filename": filename
                }
                return "FAILED", filename
        
        def run_download():
            try:
                # Собираем все файлы для скачивания
                all_files = []
                for preset_id in presets_list:
                    if preset_id in PRESET_FILES:
                        all_files.extend(PRESET_FILES[preset_id])
                
                total_files = len(all_files)
                if total_files == 0:
                    download_status[task_id] = {
                        "status": "error",
                        "message": "❌ Неизвестные id пресетов. Редактируйте model_hub/catalog.json.",
                        "progress": 0,
                        "total_files": 0,
                        "current_file": 0,
                        "current_filename": "",
                    }
                    return

                # Инициализируем статус
                download_status[task_id] = {
                    "status": "running",
                    "message": f"🚀 Начато скачивание пресетов: {', '.join(presets_list)}\n📦 Всего файлов: {total_files}",
                    "progress": 0,
                    "total_files": total_files,
                    "current_file": 0,
                    "current_filename": ""
                }
                
                # Списки для итоговой сводки
                downloaded_files = []
                skipped_files = []
                failed_files = []
                
                # Скачиваем каждый файл
                for idx, (url, folder, custom_filename) in enumerate(all_files, 1):
                    dest_dir = _download_dest_dir(folder)
                    result, filename = download_file_with_progress(
                        url, dest_dir, custom_filename, idx, total_files, task_id
                    )
                    
                    if result == "DOWNLOADED":
                        downloaded_files.append(filename)
                    elif result == "SKIP":
                        skipped_files.append(filename)
                    elif result == "FAILED":
                        failed_files.append(filename)
                
                # Формируем итоговую сводку
                summary_parts = []
                summary_parts.append(f"✅ Скачивание пресетов завершено: {', '.join(presets_list)}")
                summary_parts.append("")
                
                if downloaded_files:
                    summary_parts.append(f"📥 Скачано файлов: {len(downloaded_files)}")
                    for filename in downloaded_files[:10]:  # Показываем первые 10
                        summary_parts.append(f"   ✅ {filename}")
                    if len(downloaded_files) > 10:
                        summary_parts.append(f"   ... и еще {len(downloaded_files) - 10} файлов")
                    summary_parts.append("")
                
                if skipped_files:
                    summary_parts.append(f"⏭️ Пропущено (уже существуют): {len(skipped_files)}")
                    for filename in skipped_files[:10]:  # Показываем первые 10
                        summary_parts.append(f"   ⏭️ {filename}")
                    if len(skipped_files) > 10:
                        summary_parts.append(f"   ... и еще {len(skipped_files) - 10} файлов")
                    summary_parts.append("")
                
                if failed_files:
                    summary_parts.append(f"❌ Ошибки при скачивании: {len(failed_files)}")
                    for filename in failed_files:
                        summary_parts.append(f"   ❌ {filename}")
                    summary_parts.append("")
                
                summary_message = "\n".join(summary_parts)
                
                if failed_files:
                    download_status[task_id] = {
                        "status": "error",
                        "message": summary_message,
                        "progress": 100,
                        "total_files": total_files,
                        "current_file": total_files,
                        "current_filename": ""
                    }
                else:
                    download_status[task_id] = {
                        "status": "completed",
                        "message": summary_message,
                        "progress": 100,
                        "total_files": total_files,
                        "current_file": total_files,
                        "current_filename": ""
                    }
            except Exception as e:
                download_status[task_id] = {
                    "status": "error",
                    "message": f"❌ Ошибка: {str(e)}",
                    "progress": download_status[task_id].get("progress", 0),
                    "total_files": download_status[task_id].get("total_files", 0),
                    "current_file": download_status[task_id].get("current_file", 0),
                    "current_filename": download_status[task_id].get("current_filename", "")
                }
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=run_download)
        thread.daemon = True
        thread.start()
        
        # Сохраняем статус
        download_status[task_id] = {
            "status": "running",
            "message": f"🚀 Начато скачивание пресетов: {', '.join(presets_list)}"
        }
        
        return {"message": f"🚀 Скачивание начато! ID задачи: {task_id}", "task_id": task_id}
            
    except Exception as e:
        return {"message": f"❌ Ошибка: {str(e)}"}

@app.post("/download_hf")
def download_hf(
    request: Request,
    repo: str = Form(...),
    filename: str = Form(""),
    token: str = Form(""),
    folder: str = Form("gguf"),
):
    from .guildclaw_glue import check_hub_request

    check_hub_request(request)
    try:
        # Создаем уникальный ID для отслеживания
        task_id = str(uuid.uuid4())
        
        def run_hf_download():
            try:
                target_dir = _download_dest_dir(folder)
                os.makedirs(target_dir, exist_ok=True)
                
                if filename:
                    # Скачиваем конкретный файл с прогрессом
                    # Формируем прямую ссылку на файл
                    hf_url = f"https://huggingface.co/{repo}/resolve/main/{filename}"
                    
                    # Обновляем статус - начало скачивания
                    download_status[task_id] = {
                        "status": "running",
                        "message": f"📥 Подключение к HuggingFace...",
                        "progress": 0
                    }
                    
                    # Подготавливаем заголовки
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                    hf_t = token.strip() if token else os.environ.get("HF_TOKEN", "").strip()
                    if hf_t:
                        headers["Authorization"] = f"Bearer {hf_t}"
                    
                    response = requests.get(hf_url, stream=True, headers=headers, timeout=300)
                    response.raise_for_status()
                    
                    file_path = os.path.join(target_dir, filename)
                    
                    # Получаем размер файла
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    last_update = 0
                    update_interval = 1024 * 1024 * 5  # Обновляем каждые 5MB
                    
                    # Скачиваем файл с отслеживанием прогресса
                    with open(file_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                
                                # Обновляем прогресс каждые 5MB
                                if downloaded - last_update >= update_interval or (total_size > 0 and downloaded >= total_size):
                                    last_update = downloaded
                                    
                                    if total_size > 0:
                                        percent = int((downloaded / total_size) * 100)
                                        size_mb = downloaded / (1024 * 1024)
                                        total_mb = total_size / (1024 * 1024)
                                        download_status[task_id] = {
                                            "status": "running",
                                            "message": f"📥 Скачивание: {filename} ({percent}%) - {size_mb:.1f} MB / {total_mb:.1f} MB",
                                            "progress": percent
                                        }
                                    else:
                                        size_mb = downloaded / (1024 * 1024)
                                        download_status[task_id] = {
                                            "status": "running",
                                            "message": f"📥 Скачивание: {filename} ({size_mb:.1f} MB)",
                                            "progress": 0
                                        }
                    
                    # Финальное обновление
                    size_mb = os.path.getsize(file_path) / (1024 * 1024)
                    success_msg = f"✅ Успешно загружено!\n📁 Файл: {filename}\n💾 Размер: {size_mb:.1f} MB\n📂 Путь: {target_dir}"
                    
                    download_status[task_id] = {
                        "status": "completed",
                        "message": success_msg,
                        "progress": 100
                    }
                else:
                    # Скачиваем весь репозиторий (используем huggingface_hub, так как это сложнее)
                    download_status[task_id] = {
                        "status": "running",
                        "message": f"📥 Скачивание всего репозитория {repo}...",
                        "progress": 0
                    }
                    
                    hf_t = token.strip() if token else os.environ.get("HF_TOKEN", "").strip()
                    if hf_t:
                        login(token=hf_t)
                    
                    from huggingface_hub import snapshot_download
                    snapshot_download(
                        repo_id=repo,
                        cache_dir=target_dir,
                        local_dir=target_dir,
                        local_dir_use_symlinks=False
                    )
                    
                    success_msg = f"✅ Успешно загружено!\n📁 Репозиторий: {repo}\n📂 Путь: {target_dir}"
                    
                    download_status[task_id] = {
                        "status": "completed",
                        "message": success_msg,
                        "progress": 100
                    }
                
            except Exception as e:
                error_msg = f"❌ Ошибка: {str(e)}"
                
                # Если ошибка связана с токеном, предлагаем его ввести
                if "authentication" in str(e).lower() or "token" in str(e).lower() or "401" in str(e):
                    error_msg += "\n\n💡 Попробуйте ввести API токен HuggingFace"
                
                download_status[task_id] = {
                    "status": "error",
                    "message": error_msg,
                    "progress": download_status[task_id].get("progress", 0)
                }
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=run_hf_download)
        thread.daemon = True
        thread.start()
        
        # Сохраняем статус
        download_status[task_id] = {
            "status": "running",
            "message": f"🚀 Начато скачивание с HuggingFace: {repo}",
            "progress": 0
        }
        
        return {"message": f"🚀 Скачивание начато! ID задачи: {task_id}", "task_id": task_id}
        
    except Exception as e:
        return {"message": f"❌ Ошибка: {str(e)}"}

@app.post("/download_url")
def download_url(request: Request, url: str = Form(...), folder: str = Form("gguf")):
    from .guildclaw_glue import check_hub_request

    check_hub_request(request)
    try:
        # Создаем уникальный ID для отслеживания
        task_id = str(uuid.uuid4())
        
        def run_url_download():
            try:
                target_dir = _download_dest_dir(folder)
                os.makedirs(target_dir, exist_ok=True)
                
                # Скачиваем файл по прямой ссылке с отслеживанием прогресса
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                }
                hf_env = os.environ.get("HF_TOKEN", "").strip()
                if hf_env and "huggingface.co" in url:
                    headers["Authorization"] = f"Bearer {hf_env}"
                
                # Обновляем статус - начало скачивания
                download_status[task_id] = {
                    "status": "running",
                    "message": f"📥 Подключение к серверу...",
                    "progress": 0
                }
                
                response = requests.get(url, stream=True, headers=headers, timeout=300)
                response.raise_for_status()
                
                # Получаем имя файла из URL
                filename = url.split('/')[-1]
                # Убираем параметры запроса (?download=true и т.д.)
                if '?' in filename:
                    filename = filename.split('?')[0]
                
                # Пытаемся получить имя файла из заголовков Content-Disposition
                if 'content-disposition' in response.headers:
                    import re
                    import urllib.parse
                    content_disposition = response.headers['content-disposition']
                    
                    # Ищем filename* (RFC 5987) для UTF-8 имен
                    utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition)
                    if utf8_match:
                        filename = urllib.parse.unquote(utf8_match.group(1))
                    else:
                        # Обычный filename
                        filename_match = re.search(r'filename[^;=\n]*=(([\'"]).*?\2|[^;\n]*)', content_disposition)
                        if filename_match:
                            filename = filename_match.group(1).strip('\'"')
                
                if not filename or '.' not in filename:
                    filename = "downloaded_file"
                
                file_path = os.path.join(target_dir, filename)
                
                # Получаем размер файла
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                last_update = 0
                update_interval = 1024 * 1024 * 5  # Обновляем каждые 5MB
                
                # Скачиваем файл с отслеживанием прогресса
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024*1024):  # 1MB chunks
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            
                            # Обновляем прогресс каждые 5MB
                            if downloaded - last_update >= update_interval or (total_size > 0 and downloaded >= total_size):
                                last_update = downloaded
                                
                                if total_size > 0:
                                    percent = int((downloaded / total_size) * 100)
                                    size_mb = downloaded / (1024 * 1024)
                                    total_mb = total_size / (1024 * 1024)
                                    download_status[task_id] = {
                                        "status": "running",
                                        "message": f"📥 Скачивание: {filename} ({percent}%) - {size_mb:.1f} MB / {total_mb:.1f} MB",
                                        "progress": percent
                                    }
                                else:
                                    size_mb = downloaded / (1024 * 1024)
                                    download_status[task_id] = {
                                        "status": "running",
                                        "message": f"📥 Скачивание: {filename} ({size_mb:.1f} MB)",
                                        "progress": 0
                                    }
                
                # Финальное обновление
                size_mb = os.path.getsize(file_path) / (1024 * 1024)
                success_msg = f"✅ Успешно загружено!\n🔗 Ссылка: {url}\n📄 Файл: {filename}\n💾 Размер: {size_mb:.1f} MB\n📂 Путь: {target_dir}"
                
                download_status[task_id] = {
                    "status": "completed",
                    "message": success_msg,
                    "progress": 100
                }
                
            except Exception as e:
                error_msg = f"❌ Ошибка: {str(e)}"
                download_status[task_id] = {
                    "status": "error",
                    "message": error_msg,
                    "progress": download_status[task_id].get("progress", 0)
                }
        
        # Запускаем в отдельном потоке
        thread = threading.Thread(target=run_url_download)
        thread.daemon = True
        thread.start()
        
        # Сохраняем статус
        download_status[task_id] = {
            "status": "running",
            "message": f"🚀 Начато скачивание по ссылке: {url}",
            "progress": 0
        }
        
        return {"message": f"🚀 Скачивание начато! ID задачи: {task_id}", "task_id": task_id}
        
    except Exception as e:
        return {"message": f"❌ Ошибка: {str(e)}"}


from .guildclaw_glue import register_guildclaw

register_guildclaw(app)
