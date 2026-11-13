import { escapeHtml, num, timeOfDay, dayLabel, duration } from '../format.js';
import { clearLivePreview, clock, livePreviewHtml, resetLivePreview, setLivePreview, transcriptHtml } from '../transcript.js';

const SAVE_DELAY_MS = 800;
const TABS = [['transcript', 'Transkript'], ['notes', 'Notizen']]; // the summary is hidden for now
const STATUS_LABEL = {
  recording: 'Läuft', processing: 'Wird verarbeitet …', done: 'Fertig', interrupted: 'Unterbrochen', error: 'Fehler',
};
const STATUS_BADGE = { recording: 'teal', processing: 'amber', done: '', interrupted: 'amber', error: 'red' };
const SOURCES = [
  ['desktop', 'Nur Desktop-Audio', 'Für Online-Vorlesungen und Streams. Das Mikrofon bleibt aus.'],
  ['both', 'Desktop-Audio + Mikrofon', 'Für Calls: Gegenüber und du getrennt. Mit Kopfhörern nutzen.'],
  ['mic', 'Nur Mikrofon', 'Für Gespräche im Raum.'],
];
const SOURCE_LABEL = { desktop: 'Desktop-Audio', both: 'Desktop + Mikrofon', mic: 'Mikrofon', import: 'Importiert' };
const LANGUAGES = [['de', 'Deutsch'], ['en', 'Englisch'], ['auto', 'Automatisch erkennen']];
const NEAR_BOTTOM_PX = 120;

let root;
let ctx;
let sessions = [];
let selectedId = null;
let detail = null;
let tab = 'transcript';
let query = '';
let pendingNotes = null;
let saveTimer = null;
const freshLive = () => ({ levels: {}, lag: 0, warnings: {}, finishing: false });
let live = freshLive();
let progress = {}; // session id -> 0..1 while re-run or import is busy
let ticker = null;

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head">
      <div>
        <h1 class="page-title">Notizen</h1>
        <p class="page-sub">Vorlesungen, Calls und Gespräche als Transkript. Audio und Text bleiben auf deinem Rechner.</p>
      </div>
      <div class="head-actions" id="n-actions"></div>
    </div>
    <div class="notes-layout">
      <aside class="card list-card" id="n-list" aria-label="Sitzungen"></aside>
      <section class="card notes-detail" id="n-detail" aria-live="polite"></section>
    </div>`;
  root.querySelector('#n-actions').addEventListener('click', onActionClick);
  root.querySelector('#n-list').addEventListener('click', onListClick);
  root.querySelector('#n-detail').addEventListener('click', onDetailClick);
  root.querySelector('#n-detail').addEventListener('input', onDetailInput);
  root.querySelector('#n-detail').addEventListener('keydown', onDetailKey);
  root.querySelector('#n-detail').addEventListener('focusout', onDetailBlur);
}

export async function show() {
  await reload();
}

// ---- data ------------------------------------------------------------------
async function reload() {
  try {
    sessions = await ctx.call('session_list', { limit: 200 });
    const keep = sessions.some((s) => s.id === selectedId) ? selectedId : (sessions[0]?.id ?? null);
    await select(keep);
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function select(id) {
  await flushNotes();
  selectedId = id;
  detail = id == null ? null : await ctx.call('session_get', { id });
  query = '';
  renderAll();
}

function renderAll() {
  renderActions();
  renderList();
  renderDetail();
  syncTicker();
}

const running = () => sessions.some((s) => s.status === 'recording');

// ---- engine events (pushed by the engine, see app.js) -------------------------
export function onSessionStatus(session) {
  if (!root) return;
  const before = sessions.find((s) => s.id === session.id)?.status;
  if (session.status === 'recording' && before !== 'recording') live = freshLive(); // a new recording starts clean
  if (session.status !== 'recording' && before === 'recording') { resetLivePreview(); live = freshLive(); }
  if (session.status !== 'processing') delete progress[session.id];
  const known = sessions.some((s) => s.id === session.id);
  sessions = known
    ? sessions.map((s) => (s.id === session.id ? { ...s, ...session } : s))
    : [session, ...sessions];
  if (!known && session.status === 'recording') {
    selectedId = session.id;
    detail = { ...session, segments: [] };
    tab = 'transcript';
  } else if (session.id === selectedId && detail) {
    const { notes, ...rest } = session; // the text box may hold unsaved notes, keep them
    const reloadSegments = detail.status === 'processing' && session.status === 'done';
    detail = { ...detail, ...rest };
    if (reloadSegments) { select(session.id); return; }
  }
  renderAll();
}

export function onSessionSegment({ session_id: sessionId, segment }) {
  if (!root || sessionId !== selectedId || !detail) return;
  clearLivePreview(segment.speaker);
  if (detail.segments.some((s) => s.id === segment.id)) return;
  detail = { ...detail, segments: [...detail.segments, segment] };
  if (tab === 'transcript') renderBody({ follow: true });
  renderMeta();
}

export function onSessionPreview(msg) {
  if (!root || msg.session_id !== selectedId || !detail) return;
  setLivePreview(msg);
  if (tab === 'transcript') renderBody({ follow: true });
}

export function onSessionEvent(msg) {
  if (!root) return;
  if (msg.type === 'session_progress') {
    progress[msg.session_id] = msg.progress;
    if (msg.session_id === selectedId) renderProgress();
    return;
  }
  if (msg.session_id !== selectedId || !detail) return;
  if (msg.type === 'session_levels') {
    live.levels = msg.levels;
    live.lag = msg.lag_s;
    renderMeters();
  } else if (msg.type === 'session_warning') {
    if (msg.kind === 'clear') delete live.warnings[msg.clears];
    else live.warnings[msg.kind] = msg.text;
    renderLivePanel();
  } else if (msg.type === 'session_finishing') {
    live.finishing = true;
    live.lag = msg.remaining_s;
    renderLivePanel();
    renderActions();
  }
}

// ---- rendering -------------------------------------------------------------------
function renderActions() {
  const box = root.querySelector('#n-actions');
  if (running()) {
    box.innerHTML = live.finishing
      ? '<button class="btn btn-light" disabled><span class="ic i-loader-circle spin"></span>Wird abgeschlossen …</button>'
      : '<button class="btn btn-stop" id="n-stop"><span class="ic i-square"></span>Aufnahme beenden</button>';
    return;
  }
  box.innerHTML = `
    <button class="btn btn-ghost" id="n-import" title="Eine Aufnahme aus OBS oder einer anderen App transkribieren"><span class="ic i-upload"></span>Aufnahme importieren</button>
    <button class="btn btn-light" id="n-start"><span class="ic i-mic"></span>Neue Sitzung</button>`;
}

function renderList() {
  const box = root.querySelector('#n-list');
  if (!sessions.length) {
    box.innerHTML = '<div class="empty"><p class="serif">Noch keine Sitzung</p><p>Starte eine Aufnahme oben rechts.</p></div>';
    return;
  }
  box.innerHTML = sessions.map((s) => `
    <button class="list-row session-row${s.id === selectedId ? ' selected' : ''}" data-id="${s.id}">
      <span class="session-main">
        <b>${escapeHtml(s.title || 'Sitzung')}</b>
        <small>${dayLabel(s.started_at)} · ${timeOfDay(s.started_at)}${s.ended_at ? ` · ${clock(s.ended_at - s.started_at)}` : ''}</small>
      </span>
      <span class="badge ${STATUS_BADGE[s.status] || ''}">${s.status === 'recording' ? '<i class="live-dot"></i>' : ''}${escapeHtml(STATUS_LABEL[s.status] || s.status)}</span>
    </button>`).join('');
}

function renderDetail() {
  const box = root.querySelector('#n-detail');
  if (!detail) {
    box.innerHTML = `<div class="empty"><p class="serif">Keine Sitzung ausgewählt</p>
      <p>Für eine Online-Vorlesung: „Neue Sitzung“ und „Nur Desktop-Audio“ wählen.</p></div>`;
    return;
  }
  const recording = detail.status === 'recording';
  box.innerHTML = `
    <header class="notes-head">
      <div class="notes-head-main">
        <h2 class="serif notes-title" id="n-title" contenteditable="${recording ? 'false' : 'true'}" spellcheck="false" title="${recording ? '' : 'Zum Umbenennen klicken'}">${escapeHtml(detail.title || 'Sitzung')}</h2>
        <p class="hint-text" id="n-meta">${escapeHtml(meta())}</p>
        <div class="tag-row">${chipsHtml()}</div>
      </div>
      <div class="notes-head-actions">${recording ? '' : actionsHtml()}</div>
    </header>
    <div id="n-live">${recording ? livePanelHtml() : ''}</div>
    <div id="n-progress">${progressHtml()}</div>
    <div class="tabs notes-tabs" role="tablist">
      ${TABS.map(([key, label]) => `<button role="tab" data-tab="${key}" aria-selected="${key === tab}" class="${key === tab ? 'active' : ''}">${label}</button>`).join('')}
    </div>
    <div class="notes-tools" id="n-tools">${tab === 'transcript' ? searchHtml() : ''}</div>
    <div class="notes-body" id="n-body"></div>`;
  applyProgress();
  renderMeters();
  renderBody({ follow: recording });
}

function chipsHtml() {
  const chips = [];
  if (detail.source) chips.push(`<span class="tag">${escapeHtml(SOURCE_LABEL[detail.source] || detail.source)}</span>`);
  if (detail.language) chips.push(`<span class="tag">${escapeHtml((LANGUAGES.find(([k]) => k === detail.language) || [0, detail.language])[1])}</span>`);
  const stt = detail.stt || {};
  if (stt.model) {
    const cpu = stt.device === 'cpu';
    chips.push(`<span class="tag${stt.fallback ? ' tag-warn' : ''}" title="${stt.fallback ? 'Die Grafikkarte ist nicht nutzbar, das Transkript wird ungenauer.' : 'Spracherkennung'}">${escapeHtml(stt.model)} · ${cpu ? 'CPU' : 'GPU'}</span>`);
  }
  if (detail.terms) chips.push(`<span class="tag tag-soft" title="Fachbegriffe">${escapeHtml(detail.terms)}</span>`);
  return chips.join('');
}

function actionsHtml() {
  const busy = detail.busy || detail.status === 'processing';
  const hasAudio = detail.audio && Object.keys(detail.audio).length > 0;
  const hasText = (detail.segments || []).some((s) => s.speaker !== 'system');
  return `
    <div class="btn-group">
      <button class="btn btn-ghost btn-sm" data-export="md" ${hasText ? '' : 'disabled'} title="Als Markdown-Datei speichern"><span class="ic i-file-down"></span>Markdown</button>
      <button class="btn btn-ghost btn-sm" data-export="txt" ${hasText ? '' : 'disabled'} title="Als Textdatei speichern"><span class="ic i-file-text"></span>Text</button>
      <button class="btn btn-light btn-sm" data-copy ${hasText ? '' : 'disabled'} title="Ganzes Transkript als Markdown kopieren"><span class="ic i-copy"></span>Alles kopieren</button>
    </div>
    <div class="btn-group">
      <button class="icon-btn" data-rerun ${hasAudio && !busy ? '' : 'disabled'} title="${hasAudio ? 'Transkript aus der Audiodatei neu erzeugen' : 'Keine Audiodatei vorhanden'}" aria-label="Transkript neu erzeugen"><span class="ic i-refresh-cw"></span></button>
      <button class="icon-btn" data-reveal ${hasAudio ? '' : 'disabled'} title="Audiodatei im Explorer zeigen" aria-label="Audiodatei zeigen"><span class="ic i-folder-open"></span></button>
      <button class="icon-btn danger" data-del ${busy ? 'disabled' : ''} title="Sitzung löschen" aria-label="Sitzung löschen"><span class="ic i-trash-2"></span></button>
    </div>`;
}

function livePanelHtml() {
  const streams = detail.source === 'desktop' ? ['them'] : detail.source === 'mic' ? ['you'] : ['them', 'you'];
  const meters = streams.map((sp) => `
    <div class="meter" data-meter="${sp}">
      <span class="meter-label">${sp === 'them' ? 'Desktop' : 'Mikrofon'}</span>
      <span class="meter-track"><i></i></span>
    </div>`).join('');
  const warnings = Object.values(live.warnings);
  if (detail.stt?.fallback) warnings.unshift('Die Grafikkarte ist nicht nutzbar: Murmel nutzt das kleine CPU-Modell, das Transkript wird ungenauer. NVIDIA-Treiber prüfen und Murmel neu starten.');
  return `
    <div class="live-panel${warnings.length ? ' has-warning' : ''}">
      ${warnings.map((text) => `<div class="live-warning" role="alert"><span class="ic i-triangle-alert"></span>${escapeHtml(text)}</div>`).join('')}
      <div class="live-row">
        <div class="live-clock"><i class="live-dot"></i><span id="n-clock">${escapeHtml(elapsed())}</span></div>
        <div class="meters">${meters}</div>
        <span class="live-lag" id="n-lag">${lagText()}</span>
      </div>
    </div>`;
}

function lagText() {
  if (live.finishing) return live.lag > 1 ? `Wird abgeschlossen, noch ca. ${Math.ceil(live.lag)} s` : 'Wird abgeschlossen …';
  return live.lag >= 3 ? `Transkript ${Math.round(live.lag)} s hinter Live` : 'Transkript ist aktuell';
}

function progressHtml() {
  const p = progress[detail?.id];
  if (detail?.status !== 'processing' && p == null) return '';
  const pct = Math.round((p ?? 0) * 100);
  return `<div class="progress-line"><span>Transkript wird erzeugt … ${pct} %</span><span class="progress-track"><i data-pct="${pct}"></i></span></div>`;
}

function renderLivePanel() {
  const box = root.querySelector('#n-live');
  if (box && detail?.status === 'recording') box.innerHTML = livePanelHtml();
  renderMeters();
}

function renderMeters() {
  root.querySelectorAll('[data-meter]').forEach((el) => {
    const value = live.levels[el.dataset.meter] ?? 0;
    el.querySelector('i').style.width = `${Math.round(Math.min(1, value) * 100)}%`;
    el.classList.toggle('quiet', value < 0.05);
  });
  const lag = root.querySelector('#n-lag');
  if (lag) lag.textContent = lagText();
}

function renderProgress() {
  const box = root.querySelector('#n-progress');
  if (box) box.innerHTML = progressHtml();
  applyProgress();
}

// the app's CSP forbids inline style attributes, so the bar width is set through the DOM
function applyProgress() {
  root.querySelectorAll('.progress-track i[data-pct]').forEach((el) => { el.style.width = `${el.dataset.pct}%`; });
}

function renderMeta() {
  const el = root.querySelector('#n-meta');
  if (el && detail) el.textContent = meta();
}

function searchHtml() {
  return `<label class="tab-search"><span class="ic i-search"></span><input class="search-input" id="n-search" type="search" placeholder="Im Transkript suchen" value="${escapeHtml(query)}" /></label>`;
}

function renderBody({ follow = false } = {}) {
  const body = root.querySelector('#n-body');
  if (!body || !detail) return;
  const oldList = body.querySelector('.seg-list');
  const scrollTop = oldList ? oldList.scrollTop : null;
  const nearBottom = !oldList || oldList.scrollHeight - oldList.scrollTop - oldList.clientHeight < NEAR_BOTTOM_PX;
  if (tab === 'transcript') body.innerHTML = transcriptPaneHtml();
  if (tab === 'notes') body.innerHTML = notesHtml();
  const list = body.querySelector('.seg-list');
  if (!list) return;
  if (follow && nearBottom) list.scrollTop = list.scrollHeight; // follow the live transcript unless the user scrolled up
  else if (scrollTop != null) list.scrollTop = scrollTop;
}

function transcriptPaneHtml() {
  const needle = query.trim().toLowerCase();
  const segments = (detail.segments || []).filter((s) => !needle || s.text.toLowerCase().includes(needle));
  const preview = needle ? '' : livePreviewHtml();
  if (!segments.length && !preview) {
    if (detail.status === 'recording') return empty('Die ersten Sätze erscheinen nach der ersten Sprechpause, meist nach wenigen Sekunden.');
    if (detail.status === 'processing') return empty('Das Transkript wird erzeugt …');
    return empty(needle ? 'Keine Treffer.' : 'In dieser Sitzung wurde nichts erkannt.');
  }
  return `<div class="seg-list">${transcriptHtml(segments)}${preview}</div>`;
}

function notesHtml() {
  return `
    <textarea class="textarea notes-editor" id="n-notes" placeholder="Eigene Notizen zu dieser Sitzung …">${escapeHtml(detail.notes || '')}</textarea>
    <span class="hint-text">Wird automatisch gespeichert und beim Export mitgenommen.</span>`;
}

// ---- live clock --------------------------------------------------------------------
function syncTicker() {
  const needed = detail?.status === 'recording';
  if (needed && !ticker) {
    ticker = setInterval(() => {
      const el = root.querySelector('#n-clock');
      if (el && detail?.status === 'recording') el.textContent = elapsed();
    }, 1000);
  } else if (!needed && ticker) {
    clearInterval(ticker);
    ticker = null;
  }
}

// ---- start dialog -----------------------------------------------------------------
function openStartDialog() {
  const s = ctx.settings || {};
  const source = s.session_source || 'both';
  const lang = s.language || 'de';
  const { el, close } = ctx.modal(`
    <h3>Neue Sitzung</h3>
    <form class="start-form" id="start-form">
      <label class="field"><span>Titel</span>
        <input class="input" name="title" maxlength="200" placeholder="z. B. Lineare Algebra II – Vorlesung 5" autocomplete="off" /></label>
      <fieldset class="field"><legend>Was soll aufgenommen werden?</legend>
        ${SOURCES.map(([key, label, hint]) => `
          <label class="source-option"><input type="radio" name="source" value="${key}" ${key === source ? 'checked' : ''} />
            <span><b>${label}</b><small>${hint}</small></span></label>`).join('')}
      </fieldset>
      <label class="field"><span>Sprache</span>
        <select class="input" name="language">${LANGUAGES.map(([k, l]) => `<option value="${k}" ${k === lang ? 'selected' : ''}>${l}</option>`).join('')}</select></label>
      <label class="field"><span>Fachbegriffe <small>(optional, mit Komma getrennt)</small></span>
        <textarea class="textarea" name="terms" rows="2" placeholder="Eigenwert, Diagonalisierung, Jordan-Normalform"></textarea></label>
      <div id="start-stt"></div>
      <label class="source-option"><input type="checkbox" name="live" ${s.session_live_text === false ? '' : 'checked'} />
        <span><b>Live-Text beim Sprechen</b><small>Der Satz erscheint, während er gesprochen wird. Braucht etwas mehr Rechenleistung der Grafikkarte.</small></span></label>
      <p class="hint-text">Tipp: Starte die Sitzung erst, wenn Kopfhörer verbunden sind und der Ton der Vorlesung läuft.</p>
      <div class="modal-actions"><button type="button" class="btn btn-ghost" data-close>Abbrechen</button>
        <button type="submit" class="btn btn-light" id="start-ok"><span class="ic i-mic"></span>Aufnahme starten</button></div>
    </form>`);
  ctx.call('stt_info').then((stt) => {
    if (!stt?.fallback) return;
    el.querySelector('#start-stt').innerHTML = '<p class="live-warning" role="alert"><span class="ic i-triangle-alert"></span>Die Grafikkarte ist nicht nutzbar, Murmel nutzt das kleine CPU-Modell. Das Transkript wird ungenauer und kann hinterherhinken.</p>';
  }).catch(() => {});
  el.querySelector('#start-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const form = new FormData(e.target);
    const params = {
      title: String(form.get('title') || ''),
      source: String(form.get('source') || 'both'),
      language: String(form.get('language') || 'de'),
      terms: String(form.get('terms') || ''),
      live: form.get('live') === 'on',
    };
    const button = el.querySelector('#start-ok');
    button.disabled = true;
    try {
      if (params.source !== ctx.settings?.session_source || params.live !== (ctx.settings?.session_live_text !== false)) {
        // only remembers the choices for next time, must never block the recording
        await ctx.saveSettings({ session_source: params.source, session_live_text: params.live }).catch(() => {});
      }
      live = freshLive();
      const started = await ctx.call('session_start', params);
      close();
      tab = 'transcript';
      await reload();
      await select(started.id);
    } catch (err) {
      button.disabled = false;
      ctx.toast(err.message, true);
    }
  });
}

// ---- events -------------------------------------------------------------------------
async function onActionClick(e) {
  try {
    if (e.target.closest('#n-start')) {
      openStartDialog();
    } else if (e.target.closest('#n-stop')) {
      const ok = await ctx.confirm('Aufnahme beenden?', 'Die Sitzung wird gestoppt und das restliche Audio noch transkribiert.', 'Beenden');
      if (!ok) return;
      live.finishing = true;
      renderActions();
      await ctx.call('session_stop');
      await reload();
    } else if (e.target.closest('#n-import')) {
      const path = await window.murmel.pickAudioFile();
      if (!path) return;
      const session = await ctx.call('session_import', { path });
      ctx.toast('Aufnahme wird transkribiert …');
      await reload();
      await select(session.id);
    }
  } catch (err) {
    live.finishing = false;
    renderActions();
    ctx.toast(err.message, true);
  }
}

async function onListClick(e) {
  const row = e.target.closest('[data-id]');
  if (!row) return;
  try {
    await select(Number(row.dataset.id));
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function onDetailClick(e) {
  const tabButton = e.target.closest('[data-tab]');
  if (tabButton) {
    tab = tabButton.dataset.tab;
    renderDetail();
    return;
  }
  const exportButton = e.target.closest('[data-export]');
  if (exportButton) return exportTo(exportButton.dataset.export);
  if (e.target.closest('[data-copy]')) return copyAll();
  if (e.target.closest('[data-rerun]')) return rerun();
  if (e.target.closest('[data-reveal]')) return reveal();
  if (e.target.closest('[data-del]')) return remove();
}

function onDetailInput(e) {
  if (e.target.id === 'n-search') {
    query = e.target.value;
    renderBody();
  } else if (e.target.id === 'n-notes') {
    detail = { ...detail, notes: e.target.value };
    queueNotes(detail.id, e.target.value);
  }
}

function onDetailKey(e) {
  if (e.target.id !== 'n-title') return;
  if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); }
  if (e.key === 'Escape') { e.target.textContent = detail.title; e.target.blur(); }
}

async function onDetailBlur(e) {
  if (e.target.id !== 'n-title' || !detail) return;
  const title = e.target.textContent.trim();
  if (!title || title === detail.title) { e.target.textContent = detail.title; return; }
  try {
    const updated = await ctx.call('session_rename', { id: detail.id, title });
    detail = { ...detail, title: updated.title };
    sessions = sessions.map((s) => (s.id === detail.id ? { ...s, title: updated.title } : s));
    renderList();
  } catch (err) {
    e.target.textContent = detail.title;
    ctx.toast(err.message, true);
  }
}

async function exportTo(format) {
  try {
    await flushNotes();
    const { filename, content } = await ctx.call('session_export', { id: detail.id, format });
    const saved = await window.murmel.saveTextFile(filename, content, format);
    if (saved) ctx.toast(`Gespeichert: ${saved}`);
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function copyAll() {
  try {
    await flushNotes();
    const { content } = await ctx.call('session_export', { id: detail.id, format: 'md' });
    await window.murmel.writeClipboard(content);
    ctx.toast('Transkript in die Zwischenablage kopiert');
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function rerun() {
  const ok = await ctx.confirm(
    'Transkript neu erzeugen?',
    'Murmel transkribiert die gespeicherte Audiodatei noch einmal, mit Sprache und Fachbegriffen dieser Sitzung. Das bisherige Transkript wird erst ersetzt, wenn der Durchlauf fertig ist.',
    'Neu erzeugen',
  );
  if (!ok) return;
  try {
    progress[detail.id] = 0;
    detail = await ctx.call('session_retranscribe', { id: detail.id }).then((d) => ({ ...detail, ...d }));
    renderAll();
  } catch (err) {
    delete progress[detail.id];
    ctx.toast(err.message, true);
  }
}

async function reveal() {
  const file = detail.audio?.mix || detail.audio?.desktop || detail.audio?.mic;
  if (file) await window.murmel.revealFile(file);
}

async function remove() {
  const ok = await ctx.confirm('Sitzung löschen?', 'Transkript, Notizen und Audiodateien werden endgültig entfernt.');
  if (!ok) return;
  clearTimeout(saveTimer);
  pendingNotes = null;
  try {
    await ctx.call('session_delete', { id: detail.id });
    selectedId = null;
    await reload();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

// ---- notes autosave ------------------------------------------------------------------
function queueNotes(id, text) {
  pendingNotes = { id, text };
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushNotes, SAVE_DELAY_MS);
}

async function flushNotes() {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (!pendingNotes) return;
  const { id, text } = pendingNotes;
  pendingNotes = null;
  try {
    await ctx.call('session_update_notes', { id, notes: text });
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

// ---- helpers --------------------------------------------------------------------------
function empty(text) {
  return `<div class="empty"><p>${escapeHtml(text)}</p></div>`;
}

function elapsed() {
  const end = detail?.ended_at ?? Date.now() / 1000;
  return clock(Math.max(0, end - (detail?.started_at ?? end)));
}

function meta() {
  const words = (detail.segments || [])
    .filter((s) => s.speaker !== 'system')
    .reduce((n, s) => n + s.text.split(/\s+/).filter(Boolean).length, 0);
  const start = `${dayLabel(detail.started_at)}, ${timeOfDay(detail.started_at)}`;
  const length = detail.ended_at ? duration((detail.ended_at - detail.started_at) / 60) : 'läuft';
  return `${start} · ${length} · ${num(words)} Wörter`;
}
