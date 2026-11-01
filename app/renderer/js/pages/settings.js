import { escapeHtml, hotkeyLabel } from '../format.js';
import { initials } from '../auth.js';

const HOTKEY_PRESETS = ['caps lock', 'ctrl+windows', 'right ctrl', 'right alt', 'f8', 'scroll lock'];
const LANGUAGES = [
  ['de', 'Deutsch'], ['en', 'Englisch'], ['auto', 'Automatisch erkennen'], ['fr', 'Französisch'],
  ['es', 'Spanisch'], ['it', 'Italienisch'], ['nl', 'Niederländisch'], ['pl', 'Polnisch'], ['tr', 'Türkisch'],
];
const MODELS = [
  ['large-v3-turbo', 'Large v3 Turbo – schnell & genau (empfohlen)'],
  ['large-v3', 'Large v3 – maximal genau, langsamer'],
  ['medium', 'Medium – ausgewogen'],
  ['small', 'Small – sehr schnell'],
  ['base', 'Base – minimal'],
];
const BROWSER_KEY_NAMES = { Control: 'ctrl', Meta: 'windows', Alt: 'alt', AltGraph: 'alt gr', Shift: 'shift', CapsLock: 'caps lock', ' ': 'space', ScrollLock: 'scroll lock', Pause: 'pause', Insert: 'insert' };
const MODIFIERS = ['ctrl', 'windows', 'alt', 'shift'];

let root;
let ctx;

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head"><div><h1 class="page-title">Einstellungen</h1>
      <p class="page-sub">Alles läuft lokal auf deinem PC – keine Cloud, keine Kosten.</p></div></div>

    <h2 class="section-title">Account</h2>
    <div class="settings-list card">
      <div class="setting-row account-row"><div class="account-id"><span class="avatar" id="acc-avatar"></span>
        <div><b id="acc-name"></b><p class="hint-text" id="acc-email"></p></div></div>
        <button class="btn" id="acc-edit"><span class="ic i-pencil"></span>Bearbeiten</button></div>
      <div class="setting-row"><div><b>Passwort</b><p class="hint-text">Schützt deinen Verlauf und deine Stats auf diesem PC.</p></div>
        <button class="btn" id="acc-pw"><span class="ic i-key-round"></span>Ändern</button></div>
      <div class="setting-row"><div><b>Abmelden</b><p class="hint-text">Diktieren ist erst nach erneutem Anmelden wieder möglich.</p></div>
        <button class="btn" id="acc-logout"><span class="ic i-log-out"></span>Abmelden</button></div>
      <div class="setting-row"><div><b>Account löschen</b><p class="hint-text">Entfernt Verlauf, Wörterbuch, Snippets, Audio und Einstellungen endgültig.</p></div>
        <button class="btn btn-danger" id="acc-delete"><span class="ic i-trash-2"></span>Löschen</button></div>
    </div>

    <h2 class="section-title">Allgemein</h2>
    <div class="settings-list card">
      <div class="setting-row"><div><b>Dein Name</b><p class="hint-text">Für die Begrüßung.</p></div>
        <input class="input narrow" id="set-name" maxlength="40" placeholder="Name"/></div>
      <div class="setting-row"><div><b>Diktier-Taste</b><p class="hint-text">Halten = sprechen. Kurz tippen = Freihand-Modus.</p></div>
        <div class="hotkey-picker"><span class="kbd" id="set-hotkey-label"></span>
          <select class="select narrow" id="set-hotkey-preset" aria-label="Voreinstellung"></select>
          <button class="btn" id="set-hotkey-record"><span class="ic i-keyboard"></span>Aufnehmen</button></div></div>
      <div class="setting-row"><div><b>Sitzungs-Taste</b><p class="hint-text">Startet und stoppt eine lange Aufnahme für Notizen. Ohne Taste ist sie aus.</p></div>
        <div class="hotkey-picker"><span class="kbd" id="set-session-label"></span>
          <button class="btn" id="set-session-record"><span class="ic i-keyboard"></span>Aufnehmen</button>
          <button class="btn btn-ghost" id="set-session-clear" title="Sitzungs-Taste entfernen" aria-label="Sitzungs-Taste entfernen"><span class="ic i-x"></span></button></div></div>
      <div class="setting-row"><div><b>Live-Transkript</b><p class="hint-text">Zeigt beim Diktieren und in Sitzungen schon beim Sprechen mit, was du sagst. Braucht mehr Rechenleistung.</p></div>
        <label class="switch"><input type="checkbox" id="set-live"/><i></i></label></div>
      <div class="setting-row"><div><b>Tippen für Freihand-Modus</b><p class="hint-text">Kurzes Antippen startet eine Aufnahme ohne Halten.</p></div>
        <label class="switch"><input type="checkbox" id="set-tap"/><i></i></label></div>
      <div class="setting-row"><div><b>Sounds</b><p class="hint-text">Kurzer Ton bei Start und Ende.</p></div>
        <label class="switch"><input type="checkbox" id="set-sounds"/><i></i></label></div>
      <div class="setting-row"><div><b>Hintergrund leiser</b><p class="hint-text">Andere Apps (z. B. YouTube, Musik) werden während der Aufnahme leiser und danach wiederhergestellt.</p></div>
        <label class="switch"><input type="checkbox" id="set-duck"/><i></i></label></div>
      <div class="setting-row"><div><b>Mit Windows starten</b><p class="hint-text">Murmel startet unsichtbar im Tray.</p></div>
        <label class="switch"><input type="checkbox" id="set-autostart"/><i></i></label></div>
    </div>

    <h2 class="section-title">Sprache & Erkennung</h2>
    <div class="settings-list card">
      <div class="setting-row"><div><b>Sprache</b><p class="hint-text">Feste Sprache ist schneller und genauer als „Automatisch“.</p></div>
        <select class="select narrow" id="set-lang">${LANGUAGES.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></div>
      <div class="setting-row"><div><b>Mikrofon</b></div><select class="select narrow" id="set-mic"></select></div>
      <div class="setting-row"><div><b>Sprachmodell</b><p class="hint-text">Wird beim ersten Wechsel einmalig heruntergeladen.</p></div>
        <select class="select narrow" id="set-model">${MODELS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></div>
      <div class="setting-row"><div><b>Rechenwerk</b><p class="hint-text">GPU (CUDA) ist um ein Vielfaches schneller.</p></div>
        <select class="select narrow" id="set-device"><option value="auto">Automatisch</option><option value="cuda">GPU (CUDA)</option><option value="cpu">CPU</option></select></div>
      <div class="setting-row"><div><b>Genauigkeit</b><p class="hint-text">Höhere Beam-Suche = minimal genauer, etwas langsamer.</p></div>
        <div class="segmented" id="set-beam"><button data-beam="1">Schnell</button><button data-beam="3">Mittel</button><button data-beam="5">Genau</button></div></div>
    </div>

    <h2 class="section-title">Privatsphäre & Daten</h2>
    <div class="settings-list card">
      <div class="setting-row"><div><b>Zwischenablage wiederherstellen</b><p class="hint-text">Nach dem Einfügen kommt dein vorheriger Text zurück.</p></div>
        <label class="switch"><input type="checkbox" id="set-clip"/><i></i></label></div>
      <div class="setting-row"><div><b>Text in der Island zeigen</b><p class="hint-text">Ist gerade kein Textfeld aktiv, erscheint dein Diktat zum Kopieren in der Island. Funktioniert nicht überall, z. B. nicht zuverlässig in Chrome-basierten Apps.</p></div>
        <label class="switch"><input type="checkbox" id="set-copy"/><i></i></label></div>
      <div class="setting-row"><div><b>Audio speichern</b><p class="hint-text">Die letzten 200 Aufnahmen zum Nachhören im Verlauf.</p></div>
        <label class="switch"><input type="checkbox" id="set-audio"/><i></i></label></div>
      <div class="setting-row"><div><b>Datenordner</b><p class="hint-text">Verlauf, Wörterbuch, Einstellungen und Logs.</p></div>
        <button class="btn" id="set-folder"><span class="ic i-folder-open"></span>Öffnen</button></div>
    </div>
    <p class="about hint-text">Murmel · lokal mit faster-whisper · <span id="set-engine"></span></p>`;

  bind('#set-name', 'change', (e) => ({ user_name: e.target.value.trim() }));
  bind('#set-live', 'change', (e) => ({ session_live_preview: e.target.checked }));
  bind('#set-tap', 'change', (e) => ({ tap_for_hands_free: e.target.checked }));
  bind('#set-sounds', 'change', (e) => ({ sounds: e.target.checked }));
  bind('#set-duck', 'change', (e) => ({ duck_audio: e.target.checked }));
  bind('#set-lang', 'change', (e) => ({ language: e.target.value }));
  bind('#set-mic', 'change', (e) => ({ mic_device: e.target.value === '' ? null : Number(e.target.value) }));
  bind('#set-model', 'change', (e) => ({ model: e.target.value }), 'Modell wird geladen – das kann beim ersten Mal etwas dauern.');
  bind('#set-device', 'change', (e) => ({ device: e.target.value }), 'Modell wird neu geladen …');
  bind('#set-clip', 'change', (e) => ({ restore_clipboard: e.target.checked }));
  bind('#set-copy', 'change', (e) => ({ copy_fallback: e.target.checked }));
  bind('#set-audio', 'change', (e) => ({ keep_audio: e.target.checked }));
  bind('#set-hotkey-preset', 'change', (e) => ({ hotkey: e.target.value }));
  root.querySelector('#set-beam').addEventListener('click', async (e) => {
    const b = e.target.closest('[data-beam]');
    if (b) { await save({ beam_size: Number(b.dataset.beam) }); render(); }
  });
  root.querySelector('#set-hotkey-record').addEventListener('click', () => recordHotkey('hotkey', 'Neue Diktier-Taste'));
  root.querySelector('#set-session-record').addEventListener('click', () => recordHotkey('session_hotkey', 'Neue Sitzungs-Taste'));
  root.querySelector('#set-session-clear').addEventListener('click', async () => {
    if (await save({ session_hotkey: '' })) { ctx.toast('Sitzungs-Taste entfernt'); render(); }
  });
  root.querySelector('#set-autostart').addEventListener('change', async (e) => {
    e.target.checked = await window.murmel.setAutostart(e.target.checked);
  });
  root.querySelector('#set-folder').addEventListener('click', () => window.murmel.openDataDir());
  root.querySelector('#acc-edit').addEventListener('click', editProfile);
  root.querySelector('#acc-pw').addEventListener('click', changePassword);
  root.querySelector('#acc-logout').addEventListener('click', () => ctx.logout());
  root.querySelector('#acc-delete').addEventListener('click', deleteAccount);
}

function renderAccount() {
  const a = ctx.account;
  if (!a) return;
  root.querySelector('#acc-avatar').textContent = initials(a.name);
  root.querySelector('#acc-name').textContent = a.name;
  root.querySelector('#acc-email').textContent = `${a.email} · seit ${new Date(a.created_at * 1000).toLocaleDateString('de-DE')}`;
}

function editProfile() {
  const a = ctx.account;
  const { el, close } = ctx.modal(`
    <h3>Profil bearbeiten</h3>
    <div class="field"><label for="ap-name">Name</label><input class="input" id="ap-name" maxlength="40" value="${escapeHtml(a.name)}"/></div>
    <div class="field top-gap"><label for="ap-mail">E-Mail</label><input class="input" id="ap-mail" type="email" maxlength="120" value="${escapeHtml(a.email)}"/></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button><button class="btn btn-light" id="ap-save">Speichern</button></div>`);
  el.querySelector('#ap-save').addEventListener('click', async () => {
    try {
      await ctx.call('account_update', { name: el.querySelector('#ap-name').value, email: el.querySelector('#ap-mail').value });
      close();
      setTimeout(renderAccount, 50);
      ctx.toast('Profil gespeichert');
    } catch (err) {
      ctx.toast(err.message, true);
    }
  });
}

function changePassword() {
  const { el, close } = ctx.modal(`
    <h3>Passwort ändern</h3>
    <div class="field"><label for="pw-old">Aktuelles Passwort</label><input class="input" id="pw-old" type="password" autocomplete="current-password"/></div>
    <div class="field top-gap"><label for="pw-new">Neues Passwort</label><input class="input" id="pw-new" type="password" autocomplete="new-password" minlength="6"/></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button><button class="btn btn-light" id="pw-save">Ändern</button></div>`);
  el.querySelector('#pw-save').addEventListener('click', async () => {
    try {
      await ctx.call('account_password', { old: el.querySelector('#pw-old').value, new: el.querySelector('#pw-new').value });
      close();
      ctx.toast('Passwort geändert');
    } catch (err) {
      ctx.toast(err.message, true);
    }
  });
}

function deleteAccount() {
  const { el, close } = ctx.modal(`
    <h3>Account endgültig löschen?</h3>
    <p class="hint-text">Alle Daten von <b>${escapeHtml(ctx.account.name)}</b> werden von diesem PC entfernt. Das kann nicht rückgängig gemacht werden.</p>
    <div class="field top-gap"><label for="del-pw">Passwort zur Bestätigung</label><input class="input" id="del-pw" type="password" autocomplete="current-password"/></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button><button class="btn btn-danger" id="del-go">Endgültig löschen</button></div>`);
  el.querySelector('#del-go').addEventListener('click', async () => {
    try {
      await ctx.call('account_delete', { password: el.querySelector('#del-pw').value });
      close();
    } catch (err) {
      ctx.toast(err.message, true);
    }
  });
}

export async function show() {
  render();
  renderAccount();
  root.querySelector('#set-autostart').checked = await window.murmel.getAutostart();
  try {
    const mics = await ctx.call('microphones');
    const current = ctx.settings.mic_device;
    root.querySelector('#set-mic').innerHTML = ['<option value="">Systemstandard</option>',
      ...mics.map((m) => `<option value="${m.id}" ${m.id === current ? 'selected' : ''}>${escapeHtml(m.name)}</option>`)].join('');
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

export function onEngineState(msg) {
  const el = root?.querySelector('#set-engine');
  if (el) el.textContent = msg.detail || msg.state;
}

function bind(sel, event, toPatch, notice) {
  root.querySelector(sel).addEventListener(event, async (e) => {
    if (await save(toPatch(e))) {
      if (notice) ctx.toast(notice);
      render();
    }
  });
}

async function save(patch) {
  try {
    await ctx.saveSettings(patch);
    return true;
  } catch (err) {
    ctx.toast(err.message, true);
    render();
    return false;
  }
}

function render() {
  const s = ctx.settings;
  root.querySelector('#set-name').value = s.user_name;
  root.querySelector('#set-hotkey-label').textContent = hotkeyLabel(s.hotkey);
  root.querySelector('#set-session-label').textContent = s.session_hotkey ? hotkeyLabel(s.session_hotkey) : 'aus';
  const presets = HOTKEY_PRESETS.includes(s.hotkey) ? HOTKEY_PRESETS : [...HOTKEY_PRESETS, s.hotkey];
  root.querySelector('#set-hotkey-preset').innerHTML = presets
    .map((h) => `<option value="${escapeHtml(h)}" ${h === s.hotkey ? 'selected' : ''}>${escapeHtml(hotkeyLabel(h))}</option>`).join('');
  root.querySelector('#set-live').checked = s.session_live_preview;
  root.querySelector('#set-tap').checked = s.tap_for_hands_free;
  root.querySelector('#set-sounds').checked = s.sounds;
  root.querySelector('#set-duck').checked = s.duck_audio;
  root.querySelector('#set-lang').value = s.language;
  root.querySelector('#set-model').value = s.model;
  root.querySelector('#set-device').value = s.device;
  root.querySelector('#set-clip').checked = s.restore_clipboard;
  root.querySelector('#set-copy').checked = s.copy_fallback;
  root.querySelector('#set-audio').checked = s.keep_audio;
  root.querySelectorAll('#set-beam button').forEach((b) => b.classList.toggle('active', Number(b.dataset.beam) === s.beam_size));
  onEngineState(ctx.engine);
}

/** Captures a key combo in the page and saves it to the given setting. The current hotkey itself is swallowed by the engine. */
function recordHotkey(settingKey, title) {
  const { el, close } = ctx.modal(`
    <h3>${escapeHtml(title)}</h3>
    <p class="hint-text">Drücke die gewünschte Taste oder Kombination (z. B. Strg + Win). Loslassen übernimmt sie.</p>
    <div class="hotkey-capture"><span class="kbd" id="cap">…</span></div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button></div>`,
  { onClose: () => window.removeEventListener('keydown', down, true) });
  const held = new Set();
  let combo = [];
  const name = (e) => BROWSER_KEY_NAMES[e.key] || e.key.toLowerCase();
  function down(e) {
    if (e.key === 'Escape') return;
    e.preventDefault();
    held.add(name(e));
    combo = [...held].sort((a, b) => (MODIFIERS.indexOf(a) + 1 || 9) - (MODIFIERS.indexOf(b) + 1 || 9));
    el.querySelector('#cap').textContent = hotkeyLabel(combo.join('+'));
  }
  async function up(e) {
    e.preventDefault();
    window.removeEventListener('keyup', up, true);
    window.removeEventListener('keydown', down, true);
    if (!combo.length) { close(); return; }
    const picked = combo.join('+');
    if (await save({ [settingKey]: picked })) ctx.toast(`Neue Taste: ${hotkeyLabel(picked)}`);
    close();
    render();
  }
  window.addEventListener('keydown', down, true);
  window.addEventListener('keyup', up, true);
}
