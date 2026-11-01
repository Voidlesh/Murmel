// Floating session window: live transcript, own notes and summary for one recording, plus a stop button.
import { call, on } from './api.js';
import { escapeHtml } from './format.js';
import { clearLivePreview, clock, livePreviewHtml, resetLivePreview, setLivePreview, transcriptHtml } from './transcript.js';

const SAVE_DELAY_MS = 800;
const TICK_MS = 1000;
const TABS = [['transcript', 'Transkript'], ['notes', 'Notizen'], ['summary', 'Zusammenfassung']];
const STATUS_LABEL = { recording: 'Läuft', processing: 'Fasst zusammen …', done: 'Fertig', error: 'Fehler' };

let sessionId = Number(new URLSearchParams(location.search).get('session'));
let detail = null;
let tab = 'transcript';
let pendingNotes = null; // typed but not yet saved
let saveTimer = null;

const app = document.getElementById('session-app');
app.innerHTML = `
  <header class="sw-head">
    <div>
      <h1 class="sw-title" id="sw-title">Notizen</h1>
      <p class="sw-meta" id="sw-meta"></p>
    </div>
    <button class="sw-close" id="sw-close" aria-label="Fenster schließen" title="Schließen">✕</button>
  </header>
  <nav class="sw-tabs" id="sw-tabs" role="tablist">
    ${TABS.map(([key, label]) => `<button role="tab" data-tab="${key}">${label}</button>`).join('')}
  </nav>
  <section class="sw-body" id="sw-body" aria-live="polite"></section>
  <footer class="sw-foot" id="sw-foot"></footer>`;

// ---- data --------------------------------------------------------------------
async function load() {
  if (!sessionId) return;
  try {
    detail = await call('session_get', { id: sessionId });
    render();
  } catch (err) {
    app.querySelector('#sw-body').innerHTML = `<p class="sw-empty">${escapeHtml(err.message)}</p>`;
  }
}

function render() {
  if (!detail) return;
  renderHead();
  renderTabs();
  renderBody();
  renderFoot();
}

function elapsed() {
  const end = detail.ended_at ?? Date.now() / 1000;
  return clock(Math.max(0, end - detail.started_at));
}

function renderHead() {
  if (!detail) return;
  app.querySelector('#sw-title').textContent = detail.title || 'Notizen';
  const live = detail.status === 'recording' ? '<span class="live-dot"></span>' : '';
  app.querySelector('#sw-meta').innerHTML =
    `${live}${escapeHtml(STATUS_LABEL[detail.status] ?? detail.status)} · ${escapeHtml(elapsed())}`;
}

function renderTabs() {
  app.querySelectorAll('[data-tab]').forEach((btn) => {
    btn.setAttribute('aria-selected', String(btn.dataset.tab === tab));
  });
}

function renderBody() {
  const body = app.querySelector('#sw-body');
  if (tab === 'transcript') body.innerHTML = transcriptPaneHtml();
  if (tab === 'notes') body.innerHTML = `<textarea id="sw-notes" placeholder="Eigene Notizen …">${escapeHtml(pendingNotes ?? detail.notes)}</textarea>`;
  if (tab === 'summary') body.innerHTML = summaryPaneHtml();
}

function transcriptPaneHtml() {
  const segments = detail.segments || [];
  const live = livePreviewHtml();
  if (!segments.length && !live) {
    const text = detail.status === 'recording'
      ? 'Sprich los, die ersten Abschnitte erscheinen gleich.'
      : 'In dieser Sitzung wurde nichts erkannt.';
    return `<p class="sw-empty">${text}</p>`;
  }
  return `<div class="seg-list">${transcriptHtml(segments)}${live}</div>`;
}

function summaryPaneHtml() {
  if (detail.summary) {
    const tasks = detail.action_items?.length
      ? `<h4 class="tasks-head">Aufgaben</h4><ul class="task-list">${detail.action_items.map((t) => `<li>${escapeHtml(t)}</li>`).join('')}</ul>`
      : '';
    return `<div class="summary-text">${escapeHtml(detail.summary)}</div>${tasks}`;
  }
  const text = detail.status === 'recording'
    ? 'Die Zusammenfassung entsteht, sobald du die Sitzung stoppst.'
    : detail.status === 'processing' ? 'Zusammenfassung wird erstellt …' : 'Noch keine Zusammenfassung.';
  return `<p class="sw-empty">${text}</p>`;
}

function renderFoot() {
  const foot = app.querySelector('#sw-foot');
  foot.innerHTML = detail.status === 'recording' ? '<button class="sw-stop" id="sw-stop">Stoppen</button>' : '';
}

// ---- notes: save while typing, and on tab change, blur or session switch -------
async function flushNotes() {
  clearTimeout(saveTimer);
  saveTimer = null;
  if (pendingNotes === null || !detail) return;
  const notes = pendingNotes;
  pendingNotes = null;
  try {
    await call('session_update_notes', { id: sessionId, notes });
    detail = { ...detail, notes };
  } catch (err) {
    pendingNotes = notes; // keep the text, a later edit or flush retries
    app.querySelector('#sw-meta').textContent = `Notizen nicht gespeichert: ${err.message}`;
  }
}

app.addEventListener('input', (e) => {
  if (e.target.id !== 'sw-notes') return;
  pendingNotes = e.target.value;
  clearTimeout(saveTimer);
  saveTimer = setTimeout(flushNotes, SAVE_DELAY_MS);
});
window.addEventListener('blur', flushNotes);

// ---- interaction ---------------------------------------------------------------
app.addEventListener('click', async (e) => {
  const tabButton = e.target.closest('[data-tab]');
  if (tabButton) {
    await flushNotes();
    tab = tabButton.dataset.tab;
    render();
    return;
  }
  if (e.target.closest('#sw-close')) {
    await flushNotes();
    window.murmel.closeSession();
    return;
  }
  if (e.target.closest('#sw-stop')) {
    const stop = e.target.closest('#sw-stop');
    stop.disabled = true;
    try {
      await call('session_stop', {});
    } catch (err) {
      stop.disabled = false;
      app.querySelector('#sw-meta').textContent = err.message;
    }
  }
});

// ---- engine events --------------------------------------------------------------
on('session_segment', ({ session_id: id, segment }) => {
  if (!detail || id !== sessionId || detail.segments.some((s) => s.id === segment.id)) return;
  clearLivePreview(segment.speaker);
  detail = { ...detail, segments: [...detail.segments, segment] };
  if (tab === 'transcript') renderBody();
  renderHead();
});

on('session_preview', (msg) => {
  if (!detail || msg.session_id !== sessionId) return;
  setLivePreview(msg);
  if (tab === 'transcript') renderBody();
});

on('session_status', ({ session }) => {
  if (!detail || session.id !== sessionId) return;
  if (session.status !== 'recording') resetLivePreview();
  const { notes, ...rest } = session; // the text box may hold unsaved notes, keep them
  detail = { ...detail, ...rest };
  render();
});

// the island opens the window for another session while this one is still open
window.murmel.onSessionOpen(async (id) => {
  await flushNotes();
  sessionId = Number(id);
  detail = null;
  pendingNotes = null;
  resetLivePreview();
  tab = 'transcript';
  await load();
});

setInterval(() => {
  if (detail?.status === 'recording') renderHead();
}, TICK_MS);

load();
