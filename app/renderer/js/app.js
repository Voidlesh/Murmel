import { call, on } from './api.js';
import { escapeHtml } from './format.js';
import { showAuth, hideAuth, initials } from './auth.js';
import * as home from './pages/home.js';
import * as insights from './pages/insights.js';
import * as dictionary from './pages/dictionary.js';
import * as snippets from './pages/snippets.js';
import * as style from './pages/style.js';
import * as notes from './pages/notes.js';
import * as settingsPage from './pages/settings.js';

const PAGES = { home, notes, insights, dictionary, snippets, style, settings: settingsPage };
const TOAST_MS = 3200;
const THEME_KEY = 'murmel.theme.v2';
const SIDEBAR_KEY = 'murmel.sidebar';

const launchParams = new URLSearchParams(location.search);
const state = {
  settings: null,
  account: null,
  page: PAGES[launchParams.get('page')] ? launchParams.get('page') : 'home',
  engine: { state: 'loading', detail: '' },
};

const ctx = {
  call,
  on,
  toast,
  modal,
  confirm: confirmDialog,
  navigate,
  logout,
  get settings() { return state.settings; },
  get engine() { return state.engine; },
  get account() { return state.account; },
  async saveSettings(patch) {
    state.settings = await call('set_settings', { patch });
    renderOnboarding();
    return state.settings;
  },
};

// ---- storage helpers (localStorage may be unavailable) ------------------
function readPref(key, fallback) {
  try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; }
}
function writePref(key, value) {
  try { localStorage.setItem(key, value); } catch { /* per-viewer convenience only */ }
}
const accountPref = (key) => `${key}.${state.account?.id || 'none'}`;

// ---- toasts + modal ------------------------------------------------------
function toast(text, isError = false) {
  const el = document.createElement('div');
  el.className = `toast${isError ? ' error' : ''}`;
  el.textContent = text;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 220); }, isError ? TOAST_MS * 2.5 : TOAST_MS);
}

/** Opens a modal with trusted HTML; returns { el, close }. */
function modal(html, { onClose } = {}) {
  const backdrop = document.getElementById('modal');
  backdrop.innerHTML = `<div class="modal card" role="dialog" aria-modal="true">${html}</div>`;
  backdrop.hidden = false;
  const el = backdrop.firstElementChild;
  const close = () => { backdrop.hidden = true; backdrop.innerHTML = ''; document.removeEventListener('keydown', esc); onClose?.(); };
  const esc = (e) => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', esc);
  backdrop.onclick = (e) => { if (e.target === backdrop) close(); };
  el.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', close));
  el.querySelector('input, textarea, select')?.focus();
  return { el, close };
}

function confirmDialog(title, text, okLabel = 'Löschen') {
  return new Promise((resolve) => {
    let answered = false;
    const { el, close } = modal(`
      <h3>${escapeHtml(title)}</h3><p class="hint-text">${escapeHtml(text)}</p>
      <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button>
      <button class="btn btn-light" id="ok">${escapeHtml(okLabel)}</button></div>`, { onClose: () => { if (!answered) resolve(false); } });
    el.querySelector('#ok').addEventListener('click', () => { answered = true; resolve(true); close(); });
  });
}

// ---- navigation ------------------------------------------------------------
function navigate(page) {
  if (!PAGES[page]) return;
  state.page = page;
  document.querySelectorAll('[data-page]').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach((p) => p.classList.toggle('active', p.id === `page-${page}`));
  document.getElementById('panel').scrollTop = 0;
  closeAccountMenu();
  if (state.account) PAGES[page].show?.(document.getElementById(`page-${page}`), ctx);
  if (page === 'style') { writePref(accountPref('murmel.style-visited'), '1'); renderOnboarding(); }
}

// ---- engine status ---------------------------------------------------------
const STATUS_TEXT = { loading: 'Lädt …', idle: 'Bereit', recording: 'Hört zu', processing: 'Schreibt …', error: 'Fehler' };
function renderStatus() {
  const el = document.getElementById('engine-status');
  const { state: s, detail } = state.engine;
  el.dataset.state = s;
  el.title = detail || '';
  el.querySelector('span').textContent = s === 'idle' && /CUDA|CPU/.test(detail)
    ? `Bereit · ${detail.split('·').pop().trim()}` : STATUS_TEXT[s] || s;
}

// ---- onboarding checklist ----------------------------------------------------
async function renderOnboarding() {
  const box = document.getElementById('onboarding');
  if (!state.account || readPref(accountPref('murmel.onboarding'), '') === 'done') { box.innerHTML = ''; return; }
  try {
    const [history, dict, snips] = await Promise.all([call('history', { limit: 1 }), call('dictionary'), call('snippets')]);
    const steps = [
      { label: 'Erstes Diktat', done: history.length > 0, page: 'home' },
      { label: 'Wörterbuch-Eintrag', done: dict.length > 0, page: 'dictionary' },
      { label: 'Snippet anlegen', done: snips.length > 0, page: 'snippets' },
      { label: 'Stil wählen', done: readPref(accountPref('murmel.style-visited'), '') === '1', page: 'style' },
    ];
    const doneCount = steps.filter((s) => s.done).length;
    if (doneCount === steps.length) { writePref(accountPref('murmel.onboarding'), 'done'); box.innerHTML = ''; return; }
    box.innerHTML = `
      <h4>Murmel einrichten</h4>
      <div class="progress"><i></i></div>
      <ul>${steps.map((s) => `<li class="${s.done ? 'done' : ''}"><button data-goto="${s.page}">
        <span class="ic ${s.done ? 'i-circle-check' : 'i-circle'}"></span>${s.label}</button></li>`).join('')}</ul>`;
    box.querySelector('.progress i').style.width = `${(doneCount / steps.length) * 100}%`;
    box.querySelectorAll('[data-goto]').forEach((b) => b.addEventListener('click', () => navigate(b.dataset.goto)));
  } catch {
    box.innerHTML = '';
  }
}

// ---- account menu --------------------------------------------------------------
function closeAccountMenu() {
  document.querySelector('#account-menu .popover')?.remove();
}

function toggleAccountMenu() {
  const menu = document.getElementById('account-menu');
  if (menu.querySelector('.popover')) { closeAccountMenu(); return; }
  if (!state.account) return;
  const a = state.account;
  menu.insertAdjacentHTML('beforeend', `
    <div class="popover" role="menu">
      <div class="popover-head"><span class="avatar">${escapeHtml(initials(a.name))}</span>
        <span><b>${escapeHtml(a.name)}</b><small>${escapeHtml(a.email)}</small></span></div>
      <button data-act="settings" role="menuitem"><span class="ic i-user-round"></span>Account & Einstellungen</button>
      <button data-act="logout" role="menuitem"><span class="ic i-log-out"></span>Abmelden</button>
    </div>`);
  menu.querySelector('[data-act="settings"]').onclick = () => navigate('settings');
  menu.querySelector('[data-act="logout"]').onclick = () => logout();
}

async function logout() {
  closeAccountMenu();
  try {
    await call('auth_logout');
  } catch (err) {
    toast(err.message, true);
  }
}

// ---- auth gate -------------------------------------------------------------------
async function enterApp(result) {
  state.account = result.account;
  state.settings = result.settings || await call('get_settings');
  Object.entries(PAGES).forEach(([name, p]) => p.init?.(document.getElementById(`page-${name}`), ctx));
  navigate(state.page);
  renderOnboarding();
}

async function checkAuth() {
  const status = await call('auth_status');
  if (status.account) {
    hideAuth();
    if (state.account?.id !== status.account.id || !state.settings) await enterApp({ account: status.account });
    return;
  }
  state.account = null;
  state.settings = null;
  document.getElementById('onboarding').innerHTML = '';
  showAuth(document.getElementById('auth'), status, enterApp);
}

// ---- chrome wiring -----------------------------------------------------------
function applyTheme(theme, persist = true) {
  document.documentElement.dataset.theme = theme;
  document.querySelector('#btn-theme .ic').className = `ic ${theme === 'dark' ? 'i-sun' : 'i-moon'}`;
  if (persist) writePref(THEME_KEY, theme);
}

function wireChrome() {
  document.getElementById('win-min').onclick = () => window.murmel.minimize();
  document.getElementById('win-max').onclick = () => window.murmel.maximize();
  document.getElementById('win-close').onclick = () => window.murmel.close();
  document.getElementById('btn-theme').onclick = () =>
    applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  document.getElementById('btn-sidebar').onclick = () => {
    const collapsed = document.body.classList.toggle('sidebar-collapsed');
    writePref(SIDEBAR_KEY, collapsed ? '1' : '0');
  };
  document.getElementById('btn-account').onclick = (e) => { e.stopPropagation(); toggleAccountMenu(); };
  document.addEventListener('click', (e) => { if (!e.target.closest('#account-menu')) closeAccountMenu(); });
  document.querySelectorAll('[data-page]').forEach((b) => b.addEventListener('click', () => navigate(b.dataset.page)));
  window.murmel.onNavigate((page) => navigate(page));
  const themeParam = launchParams.get('theme');
  if (['dark', 'light'].includes(themeParam)) applyTheme(themeParam, false);
  else applyTheme(readPref(THEME_KEY, 'dark'));
  if (readPref(SIDEBAR_KEY, '0') === '1') document.body.classList.add('sidebar-collapsed');
}

// ---- keep Windows awake while a session records ----------------------------------
// Only the running session decides; status updates of other sessions (rename, re-run) must not release it.
let recordingId = null;
function trackRecording(session) {
  if (session.status === 'recording') recordingId = session.id;
  else if (session.id === recordingId) recordingId = null;
  window.murmel.setSessionPower?.(recordingId !== null);
}

async function syncRecordingAfterReconnect() {
  if (!state.account) { recordingId = null; window.murmel.setSessionPower?.(false); return; }
  try {
    const sessions = await call('session_list', { limit: 5 });
    recordingId = sessions.find((s) => s.status === 'recording')?.id ?? null;
    window.murmel.setSessionPower?.(recordingId !== null);
  } catch { /* the next status message corrects it */ }
}

function boot() {
  wireChrome();
  on('state', (msg) => {
    state.engine = msg;
    renderStatus();
    if (state.account) Object.values(PAGES).forEach((p) => p.onEngineState?.(msg, ctx));
  });
  on('transcript', (msg) => {
    Object.values(PAGES).forEach((p) => p.onTranscript?.(msg.item, ctx));
    renderOnboarding();
  });
  on('session_status', (msg) => {
    trackRecording(msg.session);
    Object.values(PAGES).forEach((p) => p.onSessionStatus?.(msg.session, ctx));
  });
  ['session_levels', 'session_warning', 'session_finishing', 'session_progress'].forEach((type) => {
    on(type, (msg) => Object.values(PAGES).forEach((p) => p.onSessionEvent?.(msg, ctx)));
  });
  on('session_segment', (msg) => Object.values(PAGES).forEach((p) => p.onSessionSegment?.(msg, ctx)));
  on('session_preview', (msg) => Object.values(PAGES).forEach((p) => p.onSessionPreview?.(msg, ctx)));
  on('notice', (msg) => toast(msg.text, Boolean(msg.warning)));
  on('account', (msg) => {
    if (!msg.account || msg.account.id !== state.account?.id) { checkAuth(); return; }
    state.account = msg.account;
  });
  on('connection', async (up) => {
    if (!up) { state.engine = { state: 'loading', detail: 'Engine nicht verbunden' }; renderStatus(); return; }
    state.settings = null;
    try { await checkAuth(); } catch (err) { toast(err.message, true); }
    syncRecordingAfterReconnect();
  });
}

boot();
