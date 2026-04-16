(function () {
  const LS_HUB = "guildclaw_hub_token";
  const LS_HF = "guildclaw_hf_token";

  const p = new URLSearchParams(location.search);
  const qtok = p.get("token");
  if (qtok) {
    try {
      localStorage.setItem(LS_HUB, qtok);
    } catch (e) {}
  }
  try {
    window.__GC_HUB = (qtok || localStorage.getItem(LS_HUB) || "").trim();
  } catch (e) {
    window.__GC_HUB = (qtok || "").trim();
  }
  if (qtok && window.__GC_HUB) {
    try {
      p.delete("token");
      const qs = p.toString();
      history.replaceState(null, "", location.pathname + (qs ? "?" + qs : "") + location.hash);
    } catch (e) {}
  }
  window.__GC_LS_HUB = LS_HUB;
  window.__GC_LS_HF = LS_HF;
})();

function gcFetchInit(extra) {
  const o = Object.assign({ credentials: "same-origin" }, extra || {});
  if (window.__GC_HUB) {
    o.headers = Object.assign({}, o.headers || {}, {
      Authorization: "Bearer " + window.__GC_HUB,
    });
  }
  return o;
}

function gcHubTokenStatus() {
  const el = document.getElementById("gc_hub_token_status");
  if (!el) return;
  try {
    if (window.__GC_HUB) {
      el.textContent = "Hub: токен сохранён, запросы к API идут с Bearer.";
    } else {
      el.textContent = "Hub: токен не задан — нужен, если на сервере включён MODEL_HUB_TOKEN.";
    }
  } catch (e) {
    el.textContent = "";
  }
}

function gcSaveHubToken() {
  const inp = document.getElementById("gc_hub_token_input");
  const v = (inp && inp.value.trim()) || "";
  if (!v) {
    alert("Введите токен Hub");
    return;
  }
  try {
    localStorage.setItem(window.__GC_LS_HUB, v);
  } catch (e) {
    alert("Не удалось сохранить (localStorage?)");
    return;
  }
  window.__GC_HUB = v;
  if (inp) inp.value = "";
  gcHubTokenStatus();
  if (typeof refreshGgufList === "function") refreshGgufList();
}

function gcClearHubToken() {
  try {
    localStorage.removeItem(window.__GC_LS_HUB);
  } catch (e) {}
  window.__GC_HUB = "";
  gcHubTokenStatus();
  if (typeof refreshGgufList === "function") refreshGgufList();
}

function gcSaveHfToken() {
  const inp = document.getElementById("gc_hf_token_input");
  const v = (inp && inp.value.trim()) || "";
  if (!v) {
    alert("Введите HF токен");
    return;
  }
  try {
    localStorage.setItem(window.__GC_LS_HF, v);
  } catch (e) {
    alert("Не удалось сохранить");
    return;
  }
  gcPrefillHfInputs(v);
  if (inp) inp.value = "";
}

function gcClearHfToken() {
  try {
    localStorage.removeItem(window.__GC_LS_HF);
  } catch (e) {}
  const hi = document.getElementById("gc_hf_token_input");
  if (hi) hi.value = "";
  const hf = document.getElementById("hf_token");
  const hu = document.getElementById("hf_url_token");
  if (hf) hf.value = "";
  if (hu) hu.value = "";
}

function gcPrefillHfInputs(fromValue) {
  const v = fromValue;
  const hf = document.getElementById("hf_token");
  const hu = document.getElementById("hf_url_token");
  if (hf && v && !hf.value.trim()) hf.value = v;
  if (hu && v && !hu.value.trim()) hu.value = v;
}

function gcLoadSavedHf() {
  try {
    const h = localStorage.getItem(window.__GC_LS_HF);
    if (h) gcPrefillHfInputs(h);
  } catch (e) {}
}

document.addEventListener("DOMContentLoaded", function () {
  gcHubTokenStatus();
  gcLoadSavedHf();
  const urlForm = document.getElementById("hf-url-form");
  if (urlForm) {
    urlForm.addEventListener("submit", function () {
      const u = document.getElementById("hf_url_token");
      if (u && !u.value.trim()) {
        try {
          const h = localStorage.getItem(window.__GC_LS_HF);
          if (h) u.value = h;
        } catch (e) {}
      }
    });
  }
  const repoForm = document.getElementById("hf-repo-form");
  if (repoForm) {
    repoForm.addEventListener("submit", function () {
      const u = document.getElementById("hf_token");
      if (u && !u.value.trim()) {
        try {
          const h = localStorage.getItem(window.__GC_LS_HF);
          if (h) u.value = h;
        } catch (e) {}
      }
    });
  }
});

const selectedPresets = new Set();
let activeCategory = "all";

function switchTab(name) {
  document.querySelectorAll("#hub-root-tabs > .tab").forEach((t) => t.classList.remove("active"));
  document.querySelectorAll(".grid > .tab-content").forEach((c) => c.classList.remove("active"));
  const tabs = document.querySelectorAll("#hub-root-tabs > .tab");
  const idx = name === "presets" ? 0 : name === "huggingface" ? 1 : name === "guildclaw" ? 2 : -1;
  if (idx < 0 || !tabs[idx]) {
    console.warn("switchTab: неизвестное имя или нет вкладок", name, tabs.length);
    return;
  }
  tabs[idx].classList.add("active");
  const pane = document.getElementById(
    name === "presets" ? "presets-tab" : name === "huggingface" ? "huggingface-tab" : "guildclaw-tab"
  );
  if (pane) pane.classList.add("active");
  if (name === "huggingface") gcLoadSavedHf();
  if (name === "guildclaw" && typeof refreshGgufList === "function") refreshGgufList();
}

function filterByCategory(catId, ev) {
  if (ev) ev.stopPropagation();
  activeCategory = catId;
  document.querySelectorAll(".category-filter").forEach((f) => f.classList.remove("active"));
  const cur = ev
    ? ev.currentTarget
    : document.querySelector(".category-filter.all");
  if (cur) cur.classList.add("active");
  applyPresetFilters();
}

function filterPresets() {
  applyPresetFilters();
}

function applyPresetFilters() {
  const q = (document.getElementById("preset-search").value || "").toLowerCase();
  document.querySelectorAll(".preset-card").forEach((card) => {
    const cat = card.getAttribute("data-category") || "";
    const okCat = activeCategory === "all" || cat === activeCategory;
    const txt = (card.textContent || "").toLowerCase();
    const okQ = !q || txt.includes(q);
    card.classList.toggle("hidden", !(okCat && okQ));
  });
}

function togglePreset(id) {
  const card = document.querySelector('.preset-card[data-preset="' + id + '"]');
  if (!card) return;
  if (selectedPresets.has(id)) {
    selectedPresets.delete(id);
    card.classList.remove("selected");
  } else {
    selectedPresets.add(id);
    card.classList.add("selected");
  }
  const btn = document.getElementById("download-presets-btn");
  if (btn) btn.disabled = selectedPresets.size === 0;
}

function togglePresetCard(id, ev) {
  const card = document.querySelector('.preset-card[data-preset="' + id + '"]');
  if (!card) return;
  if (card.classList.contains("expanded")) {
    card.classList.remove("expanded");
  } else {
    document.querySelectorAll(".preset-card.expanded").forEach((c) => c.classList.remove("expanded"));
    card.classList.add("expanded");
  }
}

function toggleVariant(parentId, variantId) {
  const cb = document.getElementById("variant-" + variantId);
  if (cb && cb.checked) {
    selectedPresets.add(variantId);
  } else {
    selectedPresets.delete(variantId);
  }
  const btn = document.getElementById("download-presets-btn");
  if (btn) btn.disabled = selectedPresets.size === 0;
}

function downloadPresets() {
  if (selectedPresets.size === 0) return;
  const ids = Array.from(selectedPresets).join(",");
  const btn = document.getElementById("download-presets-btn");
  const result = document.getElementById("preset-result");
  const progress = document.getElementById("preset-progress");
  btn.disabled = true;
  progress.style.display = "block";
  const fd = new FormData();
  fd.append("presets", ids);
  try {
    const hf = localStorage.getItem(window.__GC_LS_HF);
    if (hf && hf.trim()) fd.append("hf_token", hf.trim());
  } catch (e) {}
  fetch("/download_presets", gcFetchInit({ method: "POST", body: fd }))
    .then((r) => r.json())
    .then((data) => {
      if (data.task_id) {
        result.textContent = data.message || "";
        pollPresetStatus(data.task_id);
      } else {
        result.textContent = data.message || "Ошибка";
        progress.style.display = "none";
        btn.disabled = selectedPresets.size === 0;
      }
    })
    .catch((e) => {
      result.textContent = "Ошибка: " + e.message;
      progress.style.display = "none";
      btn.disabled = selectedPresets.size === 0;
    });
}

function pollPresetStatus(taskId) {
  const progressFill = document.getElementById("preset-progress-fill");
  const progressText = document.getElementById("preset-progress-text");
  const result = document.getElementById("preset-result");
  const progress = document.getElementById("preset-progress");
  const btn = document.getElementById("download-presets-btn");
  fetch("/status/" + taskId, gcFetchInit())
    .then((r) => r.json())
    .then((data) => {
      if (data.status === "completed" || data.status === "error") {
        result.textContent = data.message || "";
        progress.style.display = "none";
        btn.disabled = selectedPresets.size === 0;
        if (progressFill) progressFill.style.width = "100%";
      } else if (data.status === "running") {
        const p = Math.min(100, data.progress || 0);
        if (progressFill) progressFill.style.width = p + "%";
        if (progressText) progressText.textContent = data.message || "Загрузка...";
        result.textContent = data.message || "";
        setTimeout(() => pollPresetStatus(taskId), 500);
      } else {
        setTimeout(() => pollPresetStatus(taskId), 500);
      }
    })
    .catch(() => {
      progress.style.display = "none";
      btn.disabled = selectedPresets.size === 0;
    });
}

function switchHFMethod(m) {
  const inner = document.querySelectorAll("#huggingface-tab > .tabs > .tab");
  inner.forEach((t) => t.classList.remove("active"));
  const urlForm = document.getElementById("hf-url-form");
  const repoForm = document.getElementById("hf-repo-form");
  if (m === "url") {
    if (inner[0]) inner[0].classList.add("active");
    if (urlForm) urlForm.style.display = "block";
    if (repoForm) repoForm.style.display = "none";
  } else {
    if (inner[1]) inner[1].classList.add("active");
    if (urlForm) urlForm.style.display = "none";
    if (repoForm) repoForm.style.display = "block";
  }
  gcLoadSavedHf();
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function escapeAttr(s) {
  return String(s).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
}

function refreshGgufList() {
  const el = document.getElementById("gc-gguf-list");
  if (!el) return;
  el.textContent = "Загрузка…";
  const q = window.__GC_HUB ? "?token=" + encodeURIComponent(window.__GC_HUB) : "";
  fetch("/api/models" + q, gcFetchInit())
    .then((r) => {
      if (!r.ok) {
        el.innerHTML =
          '<p style="color:var(--muted)">Нет доступа. Укажите токен Hub в блоке «Токены» или откройте <code>?token=</code>.</p>';
        return null;
      }
      return r.json();
    })
    .then((j) => {
      if (!j || !j.models) return;
      if (!j.models.length) {
        el.innerHTML =
          '<p style="color:var(--muted)">Нет .gguf — скачайте через пресеты или HuggingFace.</p>';
        return;
      }
      let h =
        '<table style="width:100%;border-collapse:collapse;font-size:14px"><tr style="text-align:left;border-bottom:1px solid #444"><th>Файл</th><th>MB</th><th></th></tr>';
      for (const m of j.models) {
        const mb = (m.bytes / 1024 / 1024).toFixed(0);
        h += "<tr><td>" + escapeHtml(m.name) + (m.active ? " <strong>(активна)</strong>" : "") + "</td><td>" + mb + "</td><td>";
        h += '<form method="post" action="/ui/activate" style="display:inline;margin-right:6px;">';
        h += '<input type="hidden" name="path" value="' + escapeAttr(m.path) + '"/>';
        if (window.__GC_HUB) {
          h += '<input type="hidden" name="token" value="' + escapeAttr(window.__GC_HUB) + '"/>';
        }
        h +=
          '<button type="submit" class="btn btn-preset" style="padding:6px 10px">Активировать</button></form>';
        h += '<form method="post" action="/ui/delete" style="display:inline" onsubmit="return confirm(\'Удалить файл?\');">';
        h += '<input type="hidden" name="name" value="' + escapeAttr(m.name) + '"/>';
        if (window.__GC_HUB) {
          h += '<input type="hidden" name="token" value="' + escapeAttr(window.__GC_HUB) + '"/>';
        }
        h +=
          '<button type="submit" class="btn" style="padding:6px 10px;background:#7f1d1d;color:#fff">Удалить</button></form>';
        h += "</td></tr>";
      }
      h += "</table>";
      el.innerHTML = h;
    });
}
