import { escapeHtml, hotkeyLabel, num, timeOfDay, dayLabel } from '../format.js';

const PAGE_SIZE = 40;
const SEARCH_DEBOUNCE_MS = 200;
const BANNER_SLIDE_MS = 2 * 60 * 60 * 1000; // a new slogan at most every two hours, checked on each visit
const BANNER_SWAP_MS = 800;                 // matches the fade in app.css
const BANNER_SLIDE_KEY = 'murmel.banner-slide';
const BANNER_LINES = [
  'Sprich, wie du <em>denkst</em>.',
  'Gedanken sind schneller als Tasten.',
  'Dein Cursor wartet. Sag einfach los.',
  'Weniger tippen, mehr <em>sagen</em>.',
  'Die besten Ideen kommen beim Reden.',
  'Ein Atemzug, ein Satz, fertig.',
  'Hauptsache gesagt. Den Rest macht <em>Murmel</em>.',
];
// Unsplash photos, free to use (https://unsplash.com/license). Laptop shots: Brooke Cagle, Good Faces,
// Wes Hicks. Nature shots: Ryan Stone, Jenn Wood, ameenfahmy.
const BANNER_PHOTOS = [
  'img/banner/laptop-1.jpg', 'img/banner/nature-1.jpg', 'img/banner/laptop-2.jpg',
  'img/banner/nature-2.jpg', 'img/banner/laptop-3.jpg', 'img/banner/nature-3.jpg',
];

let root;
let ctx;
let items = [];
let query = '';
let exhausted = false;
let playingId = null;

export function init(el, context) {
  root = el;
  ctx = context;
  render();
}

export function show() {
  refreshStats();
  loadHistory(true);
  if (advanceBannerSlide()) applyBannerSlide(true);
}

export function onTranscript(item) {
  items = [item, ...items.filter((i) => i.id !== item.id)];
  renderHistory();
  refreshStats();
}

export function onEngineState() {
  renderGreeting();
}

function render() {
  root.innerHTML = `
    <h1 class="greeting" id="greeting"></h1>
    <div class="home-grid">
      <div class="home-main">
        <article class="banner hero" id="banner">
          <div class="banner-atmos" aria-hidden="true"><i></i><i></i><i></i></div>
          <div class="banner-photo" id="banner-photo" aria-hidden="true"></div>
          <button class="banner-close" id="banner-close" aria-label="Anderen Spruch zeigen"><span class="ic i-x"></span></button>
          <h2 class="banner-line" id="banner-line">${BANNER_LINES[readBannerSlide().index]}</h2>
          <p>Halte die Taste, sprich ganz natürlich – Murmel räumt Füllwörter auf und tippt für dich, in jeder App.</p>
          <div class="banner-actions"><button class="chip-btn solid" id="banner-tips">So geht's</button></div>
        </article>
        <div class="history-head">
          <span class="section-label" id="history-label">Verlauf</span>
          <div class="search-box" id="search-box">
            <span class="ic i-search"></span>
            <input class="search-input" id="search" placeholder="Verlauf durchsuchen" aria-label="Verlauf durchsuchen" />
          </div>
        </div>
        <div id="history"></div>
        <button class="btn btn-ghost load-more" id="load-more" hidden>Mehr laden</button>
      </div>
      <aside class="home-side">
        <div class="card stats-card">
          <div class="stat-line"><span class="serif stat-num" id="s-words">0</span><span>Wörter gesamt</span></div>
          <div class="stat-line"><span class="serif stat-num" id="s-wpm">0</span><span>WPM</span></div>
          <div class="stat-line"><span class="serif stat-num" id="s-streak">0</span><span id="s-streak-label">Tage Streak</span></div>
          <div class="stats-divider"></div>
          <div class="goal">
            <div class="goal-head"><strong>Tagesziel</strong><span id="goal-text"></span></div>
            <div class="goal-bar"><i id="goal-fill"></i></div>
            <p class="hint-text" id="goal-hint"></p>
          </div>
        </div>
        <button class="card voice-teaser" id="go-voice">
          <strong>Dein Stimmprofil</strong>
          <small>Entdecke, wie du deine Stimme nutzt.</small>
          <span class="voice-teaser-row"><span class="voice-teaser-bar"><i id="voice-fill"></i></span><em id="voice-text"></em></span>
        </button>
      </aside>
    </div>`;

  renderGreeting();
  applyBannerSlide(false);
  root.querySelector('#banner-close').addEventListener('click', () => {
    advanceBannerSlide(true);
    applyBannerSlide(true);
  });
  root.querySelector('#banner-tips')?.addEventListener('click', showTips);
  root.querySelector('#go-voice').addEventListener('click', () => {
    window.dispatchEvent(new CustomEvent('murmel:insights-tab', { detail: 'voice' }));
    ctx.navigate('insights');
  });
  root.querySelector('#load-more').addEventListener('click', () => loadHistory(false));
  let timer;
  root.querySelector('#search').addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(() => { query = e.target.value.trim(); loadHistory(true); }, SEARCH_DEBOUNCE_MS);
  });
  root.querySelector('#history').addEventListener('click', onHistoryClick);
  document.getElementById('player').addEventListener('ended', () => { playingId = null; renderHistory(); });
}

function readBannerSlide() {
  try { return JSON.parse(localStorage.getItem(BANNER_SLIDE_KEY)) ?? { index: 0, at: 0 }; } catch { return { index: 0, at: 0 }; }
}

// moves to the next slogan only when the last change is older than BANNER_SLIDE_MS; returns true on change
function advanceBannerSlide(force = false) {
  const slide = readBannerSlide();
  if (!force && Date.now() - slide.at < BANNER_SLIDE_MS) return false;
  try {
    localStorage.setItem(BANNER_SLIDE_KEY, JSON.stringify({ index: (slide.index + 1) % BANNER_LINES.length, at: Date.now() }));
  } catch { /* ignore: the slogan simply stays */ }
  return true;
}

function applyBannerSlide(animate) {
  const banner = root.querySelector('#banner');
  if (!banner) return;
  const line = banner.querySelector('#banner-line');
  const photo = banner.querySelector('#banner-photo');
  const { index } = readBannerSlide();
  const setSlide = () => {
    line.innerHTML = BANNER_LINES[index];
    photo.style.backgroundImage = `url('${BANNER_PHOTOS[index % BANNER_PHOTOS.length]}')`;
  };
  if (!animate) { setSlide(); return; }
  banner.classList.add('swap');
  setTimeout(() => { setSlide(); banner.classList.remove('swap'); }, BANNER_SWAP_MS);
}

function renderGreeting() {
  const el = root?.querySelector('#greeting');
  if (!el || !ctx.settings) return;
  const name = ctx.settings.user_name ? `Hey ${escapeHtml(ctx.settings.user_name)}, ` : 'Hey, ';
  el.innerHTML = `${name}bleib im Flow mit <span class="kbd">${escapeHtml(hotkeyLabel(ctx.settings.hotkey))}</span>`;
}

function showTips() {
  const key = escapeHtml(hotkeyLabel(ctx.settings.hotkey));
  ctx.modal(`
    <h3 class="serif">So diktierst du mit Murmel</h3>
    <ol class="tips">
      <li><span class="kbd">${key}</span> <b>halten</b>, sprechen, loslassen – der Text erscheint dort, wo dein Cursor ist.</li>
      <li><span class="kbd">${key}</span> <b>kurz tippen</b> für den Freihand-Modus, erneut tippen zum Beenden.</li>
      <li><span class="kbd">Esc</span> bricht eine Aufnahme ab.</li>
      <li>Sag <b>„neue Zeile“</b> oder <b>„neuer Absatz“</b> für Umbrüche.</li>
      <li>Verbessere einen Eintrag im Verlauf – Murmel merkt sich die Korrektur fürs nächste Mal.</li>
    </ol>
    <div class="modal-actions"><button class="btn btn-primary" data-close>Alles klar</button></div>`);
}

async function refreshStats() {
  try {
    const s = await ctx.call('stats', { days: null });
    root.querySelector('#s-words').textContent = num(s.words);
    root.querySelector('#s-wpm').textContent = num(s.wpm);
    root.querySelector('#s-streak').textContent = num(s.streak);
    root.querySelector('#s-streak-label').textContent = s.streak === 1 ? 'Tag Streak' : 'Tage Streak';
    const goal = ctx.settings.daily_goal || 1000;
    const pct = Math.min(100, (s.today_words / goal) * 100);
    root.querySelector('#goal-fill').style.width = `${pct}%`;
    root.querySelector('#goal-text').textContent = `${num(s.today_words)} / ${num(goal)}`;
    root.querySelector('#goal-hint').textContent = pct >= 100
      ? 'Ziel erreicht – stark!'
      : `Noch ${num(goal - s.today_words)} Wörter bis zum Tagesziel`;
    const unlockAt = 2000;
    root.querySelector('#voice-fill').style.width = `${Math.min(100, (s.words / unlockAt) * 100)}%`;
    root.querySelector('#voice-text').textContent = s.words >= unlockAt
      ? 'Jetzt ansehen'
      : `Frei in ${num(unlockAt - s.words)} Wörtern`;
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function loadHistory(reset) {
  try {
    const page = await ctx.call('history', { limit: PAGE_SIZE, offset: reset ? 0 : items.length, query });
    items = reset ? page : [...items, ...page];
    exhausted = page.length < PAGE_SIZE;
    renderHistory();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

function renderHistory() {
  const box = root.querySelector('#history');
  root.querySelector('#load-more').hidden = exhausted;
  if (!items.length) {
    const key = escapeHtml(hotkeyLabel(ctx.settings?.hotkey));
    box.innerHTML = query
      ? `<div class="empty"><p class="serif">Nichts gefunden</p><p>Kein Eintrag enthält „${escapeHtml(query)}“.</p></div>`
      : `<div class="empty"><p class="serif">Noch still hier.</p><p>Halte <span class="kbd">${key}</span> gedrückt und sag etwas.</p></div>`;
    return;
  }
  const groups = new Map();
  items.forEach((it) => {
    const label = dayLabel(it.created_at);
    groups.set(label, [...(groups.get(label) || []), it]);
  });
  box.innerHTML = [...groups].map(([label, list]) => `
    <div class="day-group">
      <div class="day-label section-label">${escapeHtml(label)}</div>
      <div class="history-card card">${list.map(rowHtml).join('')}</div>
    </div>`).join('');
}

function rowHtml(it) {
  const app = it.app ? it.app.replace(/\.exe$/i, '') : '';
  const playing = playingId === it.id;
  return `
    <div class="h-row" data-id="${it.id}">
      <div class="h-meta"><span>${timeOfDay(it.created_at)}</span>${app ? `<small>${escapeHtml(app)}</small>` : ''}</div>
      <div class="h-text">${escapeHtml(it.text)}</div>
      <div class="h-actions">
        ${it.audio_path ? `<button class="icon-btn" data-act="play" title="${playing ? 'Stopp' : 'Anhören'}"><span class="ic ${playing ? 'i-pause' : 'i-play'}"></span></button>` : ''}
        <button class="icon-btn" data-act="copy" title="Kopieren"><span class="ic i-copy"></span></button>
        <button class="icon-btn" data-act="edit" title="Verbessern"><span class="ic i-pencil"></span></button>
        <button class="icon-btn danger" data-act="delete" title="Löschen"><span class="ic i-trash-2"></span></button>
      </div>
    </div>`;
}

async function onHistoryClick(e) {
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const row = btn.closest('.h-row');
  const id = Number(row.dataset.id);
  const item = items.find((i) => i.id === id);
  try {
    if (btn.dataset.act === 'copy') await copy(item, btn);
    if (btn.dataset.act === 'play') await play(item);
    if (btn.dataset.act === 'edit') startEdit(row, item);
    if (btn.dataset.act === 'delete' && await ctx.confirm('Eintrag löschen?', 'Text und Audio werden entfernt.')) {
      await ctx.call('delete_transcript', { id });
      items = items.filter((i) => i.id !== id);
      renderHistory();
      refreshStats();
    }
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

async function copy(item, btn) {
  await navigator.clipboard.writeText(item.text);
  btn.querySelector('.ic').className = 'ic i-copy-check';
  setTimeout(() => { btn.querySelector('.ic').className = 'ic i-copy'; }, 1200);
}

async function play(item) {
  const player = document.getElementById('player');
  if (playingId === item.id) {
    player.pause();
    playingId = null;
  } else {
    const url = await ctx.call('audio', { id: item.id });
    if (!url) { ctx.toast('Audio nicht mehr vorhanden', true); return; }
    player.src = url;
    await player.play();
    playingId = item.id;
  }
  renderHistory();
}

function startEdit(row, item) {
  const textEl = row.querySelector('.h-text');
  row.classList.add('editing');
  textEl.innerHTML = `
    <textarea class="textarea edit-area" aria-label="Text verbessern">${escapeHtml(item.text)}</textarea>
    <div class="edit-actions">
      <span class="hint-text">Korrekturen landen automatisch im Wörterbuch.</span>
      <button class="btn btn-ghost" data-edit="cancel">Abbrechen</button>
      <button class="btn btn-primary" data-edit="save"><span class="ic i-check"></span>Speichern</button>
    </div>`;
  const area = textEl.querySelector('textarea');
  area.focus();
  area.setSelectionRange(area.value.length, area.value.length);
  textEl.querySelector('[data-edit="cancel"]').onclick = (e) => { e.stopPropagation(); renderHistory(); };
  textEl.querySelector('[data-edit="save"]').onclick = async (e) => {
    e.stopPropagation();
    try {
      const res = await ctx.call('edit_transcript', { id: item.id, text: area.value });
      items = items.map((i) => (i.id === item.id ? res.item : i));
      renderHistory();
      if (res.learned.length) {
        ctx.toast(`Gelernt: ${res.learned.map((l) => `${l.wrong} → ${l.right}`).join(', ')}`);
      }
    } catch (err) {
      ctx.toast(err.message, true);
    }
  };
}
