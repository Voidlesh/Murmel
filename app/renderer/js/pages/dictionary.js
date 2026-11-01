import { escapeHtml } from '../format.js';

const FILTERS = [
  { key: 'all', label: 'Alle' },
  { key: 'words', label: 'Wörter' },
  { key: 'corrections', label: 'Korrekturen' },
  { key: 'auto', label: 'Auto-gelernt' },
];
const BANNER_KEY = 'murmel.dict-banner';
const MAX_IMPORT = 500;

let root;
let ctx;
let entries = [];
let filter = 'all';
let query = '';
let newestFirst = true;
let searchOpen = false;

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head">
      <h1 class="page-title">Wörterbuch</h1>
      <div class="head-actions">
        <button class="btn btn-light" id="d-import">Importieren</button>
        <button class="btn btn-light" id="d-new">Neu</button>
      </div>
    </div>
    <div class="tabs" id="d-tabs">
      ${FILTERS.map((f) => `<button data-f="${f.key}">${f.label}</button>`).join('')}
      <div class="tab-tools">
        <div class="tab-search" id="d-search-wrap" hidden><input class="search-input" id="d-search" placeholder="Suchen …" aria-label="Wörterbuch durchsuchen"/></div>
        <button class="icon-btn" id="d-search-btn" title="Suchen" aria-label="Suchen"><span class="ic i-search"></span></button>
        <button class="icon-btn" id="d-sort" title="Sortierung" aria-label="Sortierung umkehren"><span class="ic i-arrow-up-down"></span></button>
        <button class="icon-btn" id="d-refresh" title="Aktualisieren" aria-label="Aktualisieren"><span class="ic i-refresh-cw"></span></button>
      </div>
    </div>
    <div id="d-banner"></div>
    <div class="card list-card" id="d-list"></div>`;

  root.querySelector('#d-new').addEventListener('click', () => openEditor());
  root.querySelector('#d-import').addEventListener('click', openImport);
  root.querySelector('#d-tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-f]');
    if (b) { filter = b.dataset.f; render(); }
  });
  root.querySelector('#d-search-btn').addEventListener('click', () => {
    searchOpen = !searchOpen;
    root.querySelector('#d-search-wrap').hidden = !searchOpen;
    root.querySelector('#d-search-btn').classList.toggle('on', searchOpen);
    if (searchOpen) root.querySelector('#d-search').focus();
    else { query = ''; root.querySelector('#d-search').value = ''; render(); }
  });
  root.querySelector('#d-search').addEventListener('input', (e) => { query = e.target.value.trim().toLowerCase(); render(); });
  root.querySelector('#d-sort').addEventListener('click', () => { newestFirst = !newestFirst; render(); });
  root.querySelector('#d-refresh').addEventListener('click', show);
  root.querySelector('#d-list').addEventListener('click', onListClick);
}

export async function show() {
  try {
    const [list, suggestions] = await Promise.all([ctx.call('dictionary'), ctx.call('dictionary_suggestions')]);
    entries = list;
    renderBanner(suggestions);
    render();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

function bannerHidden() {
  try { return localStorage.getItem(BANNER_KEY) === '1'; } catch { return false; }
}

function renderBanner(suggestions) {
  const box = root.querySelector('#d-banner');
  if (bannerHidden()) { box.innerHTML = ''; return; }
  const chips = [...new Set([ctx.account?.name, ...suggestions].filter(Boolean))]
    .filter((w) => !entries.some((e) => (e.replacement || e.word).toLowerCase() === w.toLowerCase()))
    .slice(0, 4);
  box.innerHTML = `
    <article class="banner">
      <button class="banner-close" id="d-banner-close" aria-label="Ausblenden"><span class="ic i-x"></span></button>
      <h2>Murmel schreibt, wie <em>du</em> schreibst.</h2>
      <p>Korrigiere ein Wort einmal oder füge es hier hinzu – so werden deine <b>Namen, Fachbegriffe und Insider</b> in jedem Diktat richtig geschrieben.</p>
      <div class="banner-actions">
        <button class="chip-btn solid" data-add="">Neues Wort</button>
        ${chips.map((c) => `<button class="chip-btn" data-add="${escapeHtml(c)}">${escapeHtml(c)}</button>`).join('')}
      </div>
    </article>`;
  box.querySelector('#d-banner-close').addEventListener('click', () => {
    try { localStorage.setItem(BANNER_KEY, '1'); } catch { /* ignore */ }
    box.innerHTML = '';
  });
  box.querySelectorAll('[data-add]').forEach((b) => b.addEventListener('click', async () => {
    if (!b.dataset.add) { openEditor(); return; }
    await save({ word: b.dataset.add });
    b.remove();
  }));
}

function visible() {
  const list = entries.filter((d) => {
    if (filter === 'words' && d.replacement) return false;
    if (filter === 'corrections' && !d.replacement) return false;
    if (filter === 'auto' && !d.auto_learned) return false;
    if (query && !`${d.word} ${d.replacement || ''}`.toLowerCase().includes(query)) return false;
    return true;
  });
  return newestFirst ? list : [...list].reverse();
}

function render() {
  root.querySelectorAll('#d-tabs [data-f]').forEach((b) => b.classList.toggle('active', b.dataset.f === filter));
  const list = visible();
  const box = root.querySelector('#d-list');
  box.classList.toggle('is-empty', !list.length);
  if (!list.length) {
    box.innerHTML = `<div class="empty"><p class="serif">${entries.length ? 'Keine Treffer' : 'Noch keine Wörter'}</p>
      <p>${entries.length ? 'Ändere Filter oder Suche.' : 'Füge Namen oder Begriffe hinzu, die Murmel kennen soll.'}</p></div>`;
    return;
  }
  box.innerHTML = list.map((d) => `
    <div class="list-row" data-id="${d.id}">
      <span class="dict-text">${d.replacement
        ? `${escapeHtml(d.word)} <span class="arrow">→</span> ${escapeHtml(d.replacement)}`
        : escapeHtml(d.word)}</span>
      ${d.auto_learned ? '<span class="badge teal"><span class="ic i-sparkles"></span>Auto-gelernt</span>' : ''}
      <div class="row-actions">
        <button class="icon-btn" data-edit title="Bearbeiten" aria-label="Bearbeiten"><span class="ic i-pencil"></span></button>
        <button class="icon-btn danger" data-del title="Entfernen" aria-label="Entfernen"><span class="ic i-trash-2"></span></button>
      </div>
    </div>`).join('');
}

async function save(payload) {
  try {
    await ctx.call('dictionary_save', payload);
    entries = await ctx.call('dictionary');
    render();
    return true;
  } catch (err) {
    ctx.toast(err.message, true);
    return false;
  }
}

async function onListClick(e) {
  const row = e.target.closest('.list-row');
  if (!row) return;
  const entry = entries.find((d) => d.id === Number(row.dataset.id));
  if (e.target.closest('[data-edit]')) { openEditor(entry); return; }
  if (!e.target.closest('[data-del]')) return;
  try {
    await ctx.call('dictionary_delete', { id: entry.id });
    entries = entries.filter((d) => d.id !== entry.id);
    render();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

function openEditor(entry = null) {
  const right = entry ? entry.replacement || entry.word : '';
  const wrong = entry?.replacement ? entry.word : '';
  const { el, close } = ctx.modal(`
    <h3>${entry ? 'Eintrag bearbeiten' : 'Neues Wort'}</h3>
    <div class="field"><label for="de-right">Richtige Schreibweise</label>
      <input class="input" id="de-right" maxlength="80" placeholder="z. B. Kubernetes, Dr. Müller" value="${escapeHtml(right)}"/></div>
    <div class="field top-gap"><label for="de-wrong">Wird oft falsch erkannt als <span class="hint-text">(optional)</span></label>
      <input class="input" id="de-wrong" maxlength="80" placeholder="z. B. Cuba Netties" value="${escapeHtml(wrong)}"/>
      <span class="hint-text">Leer lassen, wenn Murmel das Wort einfach nur kennen soll.</span></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button>
      <button class="btn btn-light" id="de-save">Speichern</button></div>`);
  el.querySelector('#de-save').addEventListener('click', async () => {
    const r = el.querySelector('#de-right').value.trim();
    const w = el.querySelector('#de-wrong').value.trim();
    if (!r) { ctx.toast('Bitte gib die richtige Schreibweise ein.', true); return; }
    const key = w || r;
    if (!(await save(w ? { word: w, replacement: r } : { word: r }))) return;
    if (entry && entry.word.toLowerCase() !== key.toLowerCase()) {
      await ctx.call('dictionary_delete', { id: entry.id }).catch((err) => ctx.toast(err.message, true));
      entries = await ctx.call('dictionary');
      render();
    }
    close();
  });
}

function openImport() {
  const { el, close } = ctx.modal(`
    <h3>Wörter importieren</h3>
    <p class="hint-text">Ein Eintrag pro Zeile. Für Korrekturen: <code>falsch -> richtig</code></p>
    <textarea class="textarea top-gap" id="di-text" rows="8" placeholder="Kubernetes&#10;Dr. Müller&#10;git hub -> GitHub"></textarea>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button>
      <button class="btn btn-light" id="di-go">Importieren</button></div>`);
  el.querySelector('#di-go').addEventListener('click', async () => {
    const lines = el.querySelector('#di-text').value.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, MAX_IMPORT);
    let ok = 0;
    for (const line of lines) {
      const [w, r] = line.split(/\s*(?:->|→|=>)\s*/);
      try {
        await ctx.call('dictionary_save', r ? { word: w, replacement: r } : { word: w });
        ok += 1;
      } catch { /* skip invalid line */ }
    }
    close();
    ctx.toast(`${ok} von ${lines.length} Einträgen importiert`);
    show();
  });
}
