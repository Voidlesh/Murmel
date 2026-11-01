import { escapeHtml } from '../format.js';

const CATEGORIES = [
  { key: 'personal', label: 'Persönlich', icon: 'i-message-circle', desc: 'WhatsApp, Discord, Telegram …' },
  { key: 'work', label: 'Arbeit', icon: 'i-briefcase', desc: 'Slack, Teams, Notion …' },
  { key: 'email', label: 'E-Mail', icon: 'i-mail', desc: 'Outlook, Gmail, Thunderbird …' },
  { key: 'other', label: 'Alles andere', icon: 'i-globe', desc: 'Jede andere App' },
];
const TONES = [
  {
    key: 'formal', label: 'Formal', note: 'Großschreibung + Satzzeichen',
    sample: 'Hey, kommst du heute Abend auch? Ich bringe Snacks mit.',
  },
  {
    key: 'casual', label: 'Locker', note: 'Großschreibung, weniger Satzzeichen',
    sample: 'Hey, kommst du heute Abend auch? Ich bringe Snacks mit',
  },
  {
    key: 'very_casual', label: 'Sehr locker', note: 'Kleinschreibung, minimal',
    sample: 'hey, kommst du heute abend auch? ich bringe snacks mit',
  },
];
const PREVIEW_DEBOUNCE_MS = 450;

let root;
let ctx;
let category = 'personal';

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head">
      <div><h1 class="page-title">Stil</h1>
      <p class="page-sub">Wie Murmel deine Sätze formt – je nachdem, wohin du gerade schreibst.</p></div>
    </div>
    <div class="style-tabs" id="st-tabs" role="tablist">${CATEGORIES.map((c) => `
      <button role="tab" data-cat="${c.key}"><span class="ic ${c.icon}"></span><span><b>${c.label}</b><small>${c.desc}</small></span></button>`).join('')}
    </div>
    <div class="tone-grid" id="st-tones"></div>
    <div class="card card-pad apps-card">
      <div class="row-between"><div><h3>Apps in dieser Kategorie</h3>
        <p class="hint-text">Prozessname (z. B. <code>slack.exe</code>) oder ein Wort aus dem Fenstertitel (z. B. <code>Gmail</code>).</p></div></div>
      <div class="chips" id="st-apps"></div>
      <form class="chip-form" id="st-app-form" autocomplete="off">
        <input class="input" id="st-app-input" placeholder="App oder Titel-Wort hinzufügen" maxlength="60"/>
        <button class="btn" type="submit"><span class="ic i-plus"></span>Hinzufügen</button>
      </form>
    </div>

    <h2 class="section-title">Feinschliff</h2>
    <div class="settings-list card">
      <div class="setting-row"><div><b>Füllwörter entfernen</b><p class="hint-text">„äh“, „ähm“, „hm“ verschwinden automatisch.</p></div>
        <label class="switch"><input type="checkbox" id="st-fillers"/><i></i></label></div>
      <div class="setting-row"><div><b>Sprachbefehle</b><p class="hint-text">„neue Zeile“ und „neuer Absatz“ erzeugen Umbrüche.</p></div>
        <label class="switch"><input type="checkbox" id="st-commands"/><i></i></label></div>
      <div class="setting-row"><div><b>KI-Feinschliff</b> <span class="badge amber">lokal</span>
        <p class="hint-text">Ein lokales Sprachmodell korrigiert Grammatik, Satzbau und Selbstkorrekturen („um drei, nein um vier“). Braucht LM Studio oder Ollama.</p></div>
        <label class="switch"><input type="checkbox" id="st-llm"/><i></i></label></div>
      <div class="llm-config" id="st-llm-config">
        <div class="form-row">
          <div class="field"><label for="st-url">Server-Adresse</label><input class="input" id="st-url"/></div>
          <div class="field"><label for="st-model">Modell</label><select class="select" id="st-model"></select></div>
        </div>
        <div class="llm-status" id="st-llm-status"></div>
        <div class="field"><label for="st-custom">Eigene Anweisungen <span class="hint-text">(optional)</span></label>
          <textarea class="textarea" id="st-custom" maxlength="600" placeholder="z. B. Benutze die Du-Form. Schreibe Zahlen immer als Ziffern."></textarea></div>
      </div>
    </div>

    <h2 class="section-title">Ausprobieren</h2>
    <div class="card card-pad tryout">
      <textarea class="textarea" id="st-try" placeholder="Tippe hier einen Satz, wie du ihn sprechen würdest – z. B. „äh ich komme so um drei, nein um vier rum“"></textarea>
      <div class="tryout-out"><span class="section-label" id="st-try-label">Ergebnis</span><p id="st-try-out" class="hint-text">—</p></div>
    </div>`;

  root.querySelector('#st-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-cat]');
    if (b) { category = b.dataset.cat; render(); runPreview(); }
  });
  root.querySelector('#st-tones').addEventListener('click', (e) => {
    const card = e.target.closest('[data-tone]');
    if (card) save({ style: { [category]: card.dataset.tone } }).then(() => { render(); runPreview(); });
  });
  root.querySelector('#st-apps').addEventListener('click', (e) => {
    const chip = e.target.closest('[data-app]');
    if (!chip) return;
    const apps = ctx.settings.style_apps[category].filter((a) => a !== chip.dataset.app);
    save({ style_apps: { [category]: apps } }).then(render);
  });
  root.querySelector('#st-app-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const input = root.querySelector('#st-app-input');
    const value = input.value.trim();
    if (!value) return;
    const apps = [...new Set([...(ctx.settings.style_apps[category] || []), value])];
    input.value = '';
    save({ style_apps: { [category]: apps } }).then(render);
  });
  bindToggle('#st-fillers', (v) => ({ remove_fillers: v }));
  bindToggle('#st-commands', (v) => ({ voice_commands: v }));
  bindToggle('#st-llm', (v) => ({ llm: { enabled: v } }), () => { renderLlm(); if (ctx.settings.llm.enabled) checkLlm(); });
  root.querySelector('#st-url').addEventListener('change', (e) => save({ llm: { base_url: e.target.value.trim() } }).then(checkLlm));
  root.querySelector('#st-model').addEventListener('change', (e) => save({ llm: { model: e.target.value } }));
  root.querySelector('#st-custom').addEventListener('change', (e) => save({ llm: { custom_instructions: e.target.value } }));
  let timer;
  root.querySelector('#st-try').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(runPreview, PREVIEW_DEBOUNCE_MS); });
}

export function show() {
  render();
  if (ctx.settings.llm.enabled) checkLlm();
}

async function save(patch) {
  try {
    await ctx.saveSettings(patch);
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

function bindToggle(sel, toPatch, after) {
  root.querySelector(sel).addEventListener('change', async (e) => { await save(toPatch(e.target.checked)); after?.(); });
}

function render() {
  const s = ctx.settings;
  root.querySelectorAll('#st-tabs [data-cat]').forEach((b) => b.classList.toggle('active', b.dataset.cat === category));
  const current = s.style[category];
  root.querySelector('#st-tones').innerHTML = TONES.map((t) => `
    <button class="card tone-card ${t.key === current ? 'selected' : ''}" data-tone="${t.key}" aria-pressed="${t.key === current}">
      <div class="tone-head"><span class="tone-title serif">${t.label}</span><span class="tone-check"><span class="ic i-check"></span></span></div>
      <p class="hint-text">${t.note}</p>
      <div class="tone-sample"><span class="sample-bubble">${escapeHtml(t.sample)}</span></div>
    </button>`).join('');
  const apps = s.style_apps[category] || [];
  root.querySelector('#st-apps').innerHTML = category === 'other'
    ? '<p class="hint-text">Alles, was keiner anderen Kategorie zugeordnet ist.</p>'
    : apps.map((a) => `<button class="chip" data-app="${escapeHtml(a)}" title="Entfernen">${escapeHtml(a)}<span class="ic i-x"></span></button>`).join('')
      || '<p class="hint-text">Keine Apps zugeordnet.</p>';
  root.querySelector('#st-app-form').hidden = category === 'other';
  root.querySelector('#st-fillers').checked = s.remove_fillers;
  root.querySelector('#st-commands').checked = s.voice_commands;
  root.querySelector('#st-llm').checked = s.llm.enabled;
  root.querySelector('#st-url').value = s.llm.base_url;
  root.querySelector('#st-custom').value = s.llm.custom_instructions;
  root.querySelector('#st-try-label').textContent = `Ergebnis · ${CATEGORIES.find((c) => c.key === category).label}`;
  renderLlm();
}

function renderLlm() {
  root.querySelector('#st-llm-config').classList.toggle('open', ctx.settings.llm.enabled);
}

async function checkLlm() {
  const status = root.querySelector('#st-llm-status');
  status.className = 'llm-status';
  status.textContent = 'Prüfe Verbindung …';
  const res = await ctx.call('llm_check').catch((err) => ({ ok: false, error: err.message }));
  const select = root.querySelector('#st-model');
  if (!res.ok) {
    status.classList.add('bad');
    status.textContent = `Nicht erreichbar – starte in LM Studio den lokalen Server (Developer → Start Server). ${res.error || ''}`;
    select.innerHTML = '<option value="">—</option>';
    return;
  }
  status.classList.add('good');
  status.textContent = `Verbunden · ${res.models.length} Modell(e) verfügbar`;
  const chosen = ctx.settings.llm.model;
  select.innerHTML = ['<option value="">Automatisch (erstes Modell)</option>',
    ...res.models.map((m) => `<option value="${escapeHtml(m)}" ${m === chosen ? 'selected' : ''}>${escapeHtml(m)}</option>`)].join('');
}

async function runPreview() {
  const text = root.querySelector('#st-try').value.trim();
  const out = root.querySelector('#st-try-out');
  if (!text) { out.textContent = '—'; out.className = 'hint-text'; return; }
  out.textContent = ctx.settings.llm.enabled ? 'KI formuliert …' : '…';
  try {
    out.textContent = await ctx.call('preview', { text, category });
    out.className = 'tryout-result';
  } catch (err) {
    out.textContent = err.message;
  }
}
