import { escapeHtml, num, timeOfDay, dayLabel, duration } from '../format.js';
import { clearLivePreview, clock, livePreviewHtml, resetLivePreview, setLivePreview, transcriptHtml } from '../transcript.js';

const SAVE_DELAY_MS = 800;
const TABS = [['transcript', 'Transkript'], ['summary', 'Zusammenfassung'], ['notes', 'Notizen']];
const STATUS_LABEL = { recording: 'Läuft', processing: 'Fasst zusammen …', done: 'Fertig', error: 'Fehler' };
const STATUS_BADGE = { recording: 'teal', processing: 'amber', done: '', error: '' };

let root;
let ctx;
let sessions = [];
let selectedId = null;
let detail = null;
let tab = 'transcript';
let query = '';
let pendingNotes = null;
let saveTimer = null;

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head">
      <div>
        <h1 class="page-title">Notizen</h1>
        <p class="page-sub">Lange Aufnahmen bleiben auf deinem Rechner. Transkript, Zusammenfassung und eigene Notizen liegen an einer Stelle.</p>
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
}

export async function show() {
  await reload();
}

// ---- data ------------------------------------------------------------------
async function reload() {
  try {
    sessions = await ctx.call('session_list', { limit: 100 });
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
  renderAll();
}

function renderAll() {
  renderActions();
  renderList();
  renderDetail();
}

// ---- engine events (pushed by the engine, see app.js) -------------------------
export function onSessionStatus(session) {
  if (!root) return;
  if (session.status !== 'recording') resetLivePreview();
  const known = sessions.some((s) => s.id === session.id);
  sessions = known
    ? sessions.map((s) => (s.id === session.id ? { ...s, ...session } : s))
    : [session, ...sessions];
  if (!known && session.status === 'recording') {
    selectedId = session.id;
    detail = { ...session, segments: [] };
  } else if (session.id === selectedId) {
    const { notes, ...rest } = session; // the text box may hold unsaved notes, keep them
    detail = { ...detail, ...rest };
  }
  renderAll();
}

export function onSessionSegment({ session_id: sessionId, segment }) {
  if (!root || sessionId !== selectedId || !detail) return;
  clearLivePreview(segment.speaker);
  if (detail.segments.some((s) => s.id === segment.id)) return;
  detail = { ...detail, segments: [...detail.segments, segment] };
  if (tab === 'transcript') renderBody();
}

export function onSessionPreview(msg) {
  if (!root || msg.session_id !== selectedId || !detail) return;
  setLivePreview(msg);
  if (tab === 'transcript') renderBody();
}

// ---- rendering -------------------------------------------------------------------
function renderActions() {
  const running = sessions.some((s) => s.status === 'recording');
  root.querySelector('#n-actions').innerHTML = running
    ? '<button class="btn btn-light" id="n-stop"><span class="ic i-square"></span>Stoppen</button>'
    : '<button class="btn btn-light" id="n-start"><span class="ic i-mic"></span>Sitzung starten</button>';
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
        <small>${dayLabel(s.started_at)} · ${timeOfDay(s.started_at)}</small>
      </span>
      <span class="badge ${STATUS_BADGE[s.status] || ''}">${escapeHtml(STATUS_LABEL[s.status] || s.status)}</span>
    </button>`).join('');
}

function renderDetail() {
  const box = root.querySelector('#n-detail');
  if (!detail) {
    box.innerHTML = '<div class="empty"><p class="serif">Keine Sitzung ausgewählt</p></div>';
    return;
  }
  box.innerHTML = `
    <header class="notes-head">
      <div>
        <h2 class="serif notes-title">${escapeHtml(detail.title || 'Sitzung')}</h2>
        <p class="hint-text">${escapeHtml(meta())}</p>
      </div>
      <button class="icon-btn danger" data-del title="Sitzung löschen" aria-label="Sitzung löschen"><span class="ic i-trash-2"></span></button>
    </header>
    <div class="tabs notes-tabs" role="tablist">
      ${TABS.map(([key, label]) => `<button role="tab" data-tab="${key}" aria-selected="${key === tab}" class="${key === tab ? 'active' : ''}">${label}</button>`).join('')}
    </div>
    <div class="notes-tools" id="n-tools">${tab === 'transcript' ? searchHtml() : ''}</div>
    <div class="notes-body" id="n-body"></div>`;
  renderBody();
}

function searchHtml() {
  return `<label class="tab-search"><span class="ic i-search"></span><input class="search-input" id="n-search" type="search" placeholder="Im Transkript suchen" value="${escapeHtml(query)}" /></label>`;
}

function renderBody() {
  const body = root.querySelector('#n-body');
  if (!body || !detail) return;
  if (tab === 'transcript') body.innerHTML = transcriptPaneHtml();
  if (tab === 'summary') body.innerHTML = summaryHtml();
  if (tab === 'notes') body.innerHTML = notesHtml();
}

function transcriptPaneHtml() {
  const needle = query.trim().toLowerCase();
  const segments = (detail.segments || []).filter((s) => !needle || s.text.toLowerCase().includes(needle));
  const live = needle ? '' : livePreviewHtml();
  if (!segments.length && !live) {
    return empty(detail.status === 'recording'
      ? 'Die ersten Abschnitte erscheinen, sobald du gesprochen hast.'
      : (needle ? 'Keine Treffer.' : 'In dieser Sitzung wurde nichts erkannt.'));
  }
  return `<div class="seg-list">${transcriptHtml(segments)}${live}</div>`;
}

function summaryHtml() {
  if (detail.summary) {
    const tasks = detail.action_items?.length
      ? `<h4 class="tasks-head">Aufgaben</h4><ul class="task-list">${detail.action_items.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>`
      : '';
    return `<div class="summary-text">${escapeHtml(detail.summary)}</div>${tasks}`;
  }
  if (detail.status === 'recording') return empty('Die Zusammenfassung entsteht, sobald du die Sitzung stoppst.');
  if (detail.status === 'processing') return empty('Zusammenfassung wird erstellt …');
  if (!ctx.settings?.llm?.enabled) {
    return empty('Aktiviere den KI-Feinschliff in den Einstellungen, damit Murmel eine Zusammenfassung erstellen kann.');
  }
  return `${empty('Noch keine Zusammenfassung.')}
    <div class="empty-action"><button class="btn btn-light" data-summarize>Zusammenfassung erstellen</button></div>`;
}

function notesHtml() {
  return `
    <textarea class="textarea notes-editor" id="n-notes" placeholder="Eigene Notizen zu dieser Sitzung …">${escapeHtml(detail.notes || '')}</textarea>
    <span class="hint-text">Wird automatisch gespeichert.</span>`;
}

// ---- events -------------------------------------------------------------------------
async function onActionClick(e) {
  try {
    if (e.target.closest('#n-start')) {
      const started = await ctx.call('session_start', {});
      await reload();
      await select(started.id);
    } else if (e.target.closest('#n-stop')) {
      await ctx.call('session_stop');
      await reload();
    }
  } catch (err) {
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
  if (e.target.closest('[data-summarize]')) return summarize();
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

async function summarize() {
  try {
    const updated = await ctx.call('session_summarize', { id: detail.id });
    detail = { ...updated, segments: detail.segments };
    renderDetail();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function remove() {
  const ok = await ctx.confirm('Sitzung löschen?', 'Transkript, Notizen und Zusammenfassung werden entfernt.');
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

function meta() {
  const words = (detail.segments || []).reduce((n, s) => n + s.text.split(/\s+/).filter(Boolean).length, 0);
  const start = `${dayLabel(detail.started_at)}, ${timeOfDay(detail.started_at)}`;
  const length = detail.ended_at ? duration((detail.ended_at - detail.started_at) / 60) : 'läuft';
  return `${start} · ${length} · ${num(words)} Wörter`;
}
