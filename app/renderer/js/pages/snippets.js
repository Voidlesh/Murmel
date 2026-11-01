import { escapeHtml } from '../format.js';

const MAX_EXPANSION = 4000;
const BANNER_KEY = 'murmel.snip-banner';

let root;
let ctx;
let snippets = [];

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head">
      <h1 class="page-title">Snippets</h1>
      <div class="head-actions"><button class="btn btn-light" id="s-new">Neu</button></div>
    </div>
    <div id="s-banner"></div>
    <div class="card list-card" id="s-list"></div>`;
  root.querySelector('#s-new').addEventListener('click', () => edit());
  root.querySelector('#s-list').addEventListener('click', onClick);
}

export async function show() {
  try {
    snippets = await ctx.call('snippets');
    renderBanner();
    render();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

function renderBanner() {
  const box = root.querySelector('#s-banner');
  let hidden = false;
  try { hidden = localStorage.getItem(BANNER_KEY) === '1'; } catch { /* ignore */ }
  if (hidden) { box.innerHTML = ''; return; }
  box.innerHTML = `
    <article class="banner">
      <button class="banner-close" id="s-banner-close" aria-label="Ausblenden"><span class="ic i-x"></span></button>
      <h2>Einmal sagen, <em>alles</em> getippt.</h2>
      <p>Sag einen kurzen Auslöser wie <b>„meine Mail“</b> – Murmel fügt den kompletten Text ein. Ideal für Adressen, Links, Signaturen und Standard-Antworten.</p>
      <div class="banner-actions">
        <button class="chip-btn solid" data-preset="">Neues Snippet</button>
        <button class="chip-btn" data-preset="meine Mail">Meine Mail</button>
        <button class="chip-btn" data-preset="meine Signatur">Signatur</button>
        <button class="chip-btn" data-preset="mein Kalender">Kalender-Link</button>
      </div>
    </article>`;
  box.querySelector('#s-banner-close').addEventListener('click', () => {
    try { localStorage.setItem(BANNER_KEY, '1'); } catch { /* ignore */ }
    box.innerHTML = '';
  });
  box.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => edit(null, b.dataset.preset)));
}

function render() {
  const box = root.querySelector('#s-list');
  if (!snippets.length) {
    box.innerHTML = '<div class="empty"><p class="serif">Noch keine Snippets</p><p>Lege oben dein erstes Snippet an.</p></div>';
    return;
  }
  box.innerHTML = snippets.map((s) => `
    <div class="list-row snippet-row" data-id="${s.id}">
      <span class="snip-trigger">${escapeHtml(s.trigger)}</span>
      <span class="arrow">→</span>
      <span class="snip-expansion">${escapeHtml(s.expansion)}</span>
      <div class="row-actions">
        <button class="icon-btn" data-edit title="Bearbeiten" aria-label="Bearbeiten"><span class="ic i-pencil"></span></button>
        <button class="icon-btn danger" data-del title="Löschen" aria-label="Löschen"><span class="ic i-trash-2"></span></button>
      </div>
    </div>`).join('');
}

async function onClick(e) {
  const row = e.target.closest('.list-row');
  if (!row) return;
  const snippet = snippets.find((s) => s.id === Number(row.dataset.id));
  if (e.target.closest('[data-edit]')) { edit(snippet); return; }
  if (e.target.closest('[data-del]') && await ctx.confirm('Snippet löschen?', `„${snippet.trigger}“ wird entfernt.`)) {
    try {
      await ctx.call('snippet_delete', { id: snippet.id });
      show();
    } catch (err) {
      ctx.toast(err.message, true);
    }
  }
}

function edit(snippet = null, presetTrigger = '') {
  const { el, close } = ctx.modal(`
    <h3>${snippet ? 'Snippet bearbeiten' : 'Neues Snippet'}</h3>
    <div class="field"><label for="sn-trigger">Wenn ich sage …</label>
      <input class="input" id="sn-trigger" maxlength="60" placeholder="meine Mail" value="${escapeHtml(snippet?.trigger || presetTrigger)}"/></div>
    <div class="field top-gap"><label for="sn-exp">… schreibe</label>
      <textarea class="textarea" id="sn-exp" maxlength="${MAX_EXPANSION}" rows="5" placeholder="deine@adresse.de">${escapeHtml(snippet?.expansion || '')}</textarea>
      <span class="hint-text">Tipp: Wähle Auslöser, die du sonst nicht im Satz sagst.</span></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button>
      <button class="btn btn-light" id="sn-save">Speichern</button></div>`);
  if (presetTrigger) el.querySelector('#sn-exp').focus();
  el.querySelector('#sn-save').addEventListener('click', async () => {
    const trigger = el.querySelector('#sn-trigger').value.trim();
    const expansion = el.querySelector('#sn-exp').value.trim();
    if (!trigger || !expansion) { ctx.toast('Bitte Auslöser und Text ausfüllen.', true); return; }
    try {
      await ctx.call('snippet_save', { trigger, expansion, id: snippet?.id ?? null });
      close();
      show();
    } catch (err) {
      ctx.toast(err.message, true);
    }
  });
}
