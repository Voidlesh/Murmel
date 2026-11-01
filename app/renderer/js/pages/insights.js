import { escapeHtml, num, duration } from '../format.js';

const BUCKETS = {
  ai: { label: 'KI-Prompts', icon: 'i-bot' },
  other: { label: 'Sonstige Aufgaben', icon: 'i-infinity' },
  personal: { label: 'Persönliche Nachrichten', icon: 'i-message-circle' },
  email: { label: 'E-Mails', icon: 'i-mail' },
  work: { label: 'Arbeits-Nachrichten', icon: 'i-message-square' },
  documents: { label: 'Dokumente', icon: 'i-file-text' },
};
const HEAT_WEEKS = 20;
const GAUGE_MAX_WPM = 220;
const RANGES = [{ label: '7 T', days: 7 }, { label: '30 T', days: 30 }, { label: '90 T', days: 90 }];
const WEEKDAY_ROWS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'];

let root;
let ctx;
let tab = new URLSearchParams(location.search).get('tab') === 'voice' ? 'voice' : 'usage';
let range = 30;
let heatOffset = 0;

export function init(el, context) {
  root = el;
  ctx = context;
  root.innerHTML = `
    <div class="page-head">
      <h1 class="page-title">Insights</h1>
      <button class="icon-btn" id="ins-customize" title="Anpassen" aria-label="Insights anpassen"><span class="ic i-sliders-horizontal"></span></button>
    </div>
    <div class="tabs" role="tablist">
      <button role="tab" data-tab="usage">Deine Nutzung</button>
      <button role="tab" data-tab="voice">Deine Stimme</button>
    </div>
    <div id="ins-body"></div>`;
  root.querySelector('.tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (b) { tab = b.dataset.tab; load(); }
  });
  root.querySelector('#ins-customize').addEventListener('click', openCustomize);
}

window.addEventListener('murmel:insights-tab', (e) => { tab = e.detail === 'voice' ? 'voice' : 'usage'; });

export function show() { load(); }
export function onTranscript() { if (root?.classList.contains('active')) load(); }

async function load() {
  root.querySelectorAll('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
  try {
    if (tab === 'usage') await renderUsage();
    else await renderVoice();
  } catch (err) {
    ctx.toast(err.message, true);
  }
}

// ---- usage tab -------------------------------------------------------------------
async function renderUsage() {
  const [all, usage, activity, ranged] = await Promise.all([
    ctx.call('stats', { days: null }),
    ctx.call('usage'),
    ctx.call('activity', { days: Math.min(366, HEAT_WEEKS * 7 + heatOffset * 28) }),
    ctx.call('stats', { days: range }),
  ]);
  const body = root.querySelector('#ins-body');
  body.innerHTML = `
    <div class="ins-row ins-top">
      <article class="card stat-box">
        <div class="big-num">${num(all.wpm)}</div>
        <div class="label">Wörter pro Minute <span class="info" data-tip="Dein durchschnittliches Sprechtempo über alle Diktate. Tippen liegt bei ~${ctx.settings.typing_wpm} WPM."><span class="ic i-info"></span></span></div>
        ${gauge(all.wpm)}
      </article>
      <article class="card stat-box">
        <div class="big-num">${num(all.fixes_words + all.fixes_dict)}</div>
        <div class="label">Fixes durch Murmel</div>
        <div class="box-divider"></div>
        <div class="fix-line"><span><b>${num(all.fixes_words)}</b> Wörter korrigiert</span><span class="info left" data-tip="Füllwörter, Grammatik und Stil, die Murmel beim Diktieren automatisch verbessert hat."><span class="ic i-info"></span></span></div>
        <div class="fix-line"><span><b>${num(all.fixes_dict)}</b> Wörterbuch-Fixes</span><span class="info left" data-tip="Wie oft ein Eintrag aus deinem Wörterbuch eine falsche Erkennung ersetzt hat."><span class="ic i-info"></span></span></div>
      </article>
      <article class="card stat-box wide">
        <div class="big-num">${num(all.words)}</div>
        <div class="label">Wörter diktiert gesamt</div>
        <div class="box-divider"></div>
        <div class="split">
          <div class="device"><span class="ic i-monitor"></span><span>Desktop<br/><b>${num(all.words)} Wörter</b></span></div>
          <div class="saved"><span class="label">Zeit gespart</span><b>${duration(all.time_saved_min)}</b>
            <span class="info left" data-tip="Geschätzt: Zeit fürs Tippen (bei ${ctx.settings.typing_wpm} WPM) minus Sprechzeit."><span class="ic i-info"></span></span></div>
        </div>
      </article>
    </div>
    <div class="ins-row ins-mid">
      <article class="card usage-card">
        <header><h2>Desktop-Nutzung</h2><span class="label">Apps gesamt | ${usage.total_apps}</span></header>
        <div class="usage-list">${usageRows(usage)}</div>
      </article>
      <article class="card streak-card">
        <header><h2>${num(all.streak)} ${all.streak === 1 ? 'Tag' : 'Tage'} Streak</h2><span class="label">Längster Streak | ${num(all.longest_streak)} ${all.longest_streak === 1 ? 'Tag' : 'Tage'}</span></header>
        ${heatmap(activity)}
      </article>
    </div>
    <article class="card daily-card">
      <header><h2>Wörter pro Tag</h2>
        <div class="segmented" id="ins-range">${RANGES.map((r) => `<button data-days="${r.days}" class="${r.days === range ? 'active' : ''}">${r.label}</button>`).join('')}</div>
      </header>
      <div class="bar-chart" id="daily">${dailyBars(ranged.daily)}</div>
      <div class="daily-foot"><span>${num(ranged.words)} Wörter · ${num(ranged.sessions)} Diktate</span><span>Heute: <b>${num(all.today_words)}</b> / ${num(ctx.settings.daily_goal)} Ziel</span></div>
    </article>`;

  body.querySelector('#ins-range').addEventListener('click', (e) => {
    const b = e.target.closest('[data-days]');
    if (b) { range = Number(b.dataset.days); renderUsage(); }
  });
  body.querySelectorAll('[data-heat]').forEach((b) => b.addEventListener('click', () => {
    heatOffset = Math.max(0, heatOffset + Number(b.dataset.heat));
    renderUsage();
  }));
  requestAnimationFrame(() => {
    body.querySelectorAll('[data-w]').forEach((el) => { el.style.width = `${el.dataset.w}%`; });
    body.querySelectorAll('[data-h]').forEach((el) => { el.style.height = `${el.dataset.h}%`; });
    body.querySelectorAll('[data-dash]').forEach((el) => { el.style.strokeDashoffset = el.dataset.dash; });
    body.querySelectorAll('.heatmap').forEach((h) => h.style.setProperty('--weeks', h.dataset.weeks));
  });
}

function gauge(wpm) {
  const r = 62;
  const len = Math.PI * r;
  const pct = Math.min(1, wpm / GAUGE_MAX_WPM);
  const factor = wpm ? (wpm / Math.max(1, ctx.settings.typing_wpm)).toFixed(1).replace('.', ',') : '0';
  return `<div class="gauge">
    <svg viewBox="0 0 156 86" aria-hidden="true">
      <path d="M16 78 A62 62 0 0 1 140 78" class="gauge-track"/>
      <path d="M16 78 A62 62 0 0 1 140 78" class="gauge-fill" stroke-dasharray="${len}" stroke-dashoffset="${len}" data-dash="${len * (1 - pct)}"/>
    </svg>
    <div class="gauge-label"><span>schneller</span><b>${factor}×</b></div>
  </div>`;
}

function usageRows(usage) {
  const sorted = [...usage.buckets].sort((a, b) => b.count - a.count);
  // bars share 55% of the row so the label always sits right after its bar
  return sorted.map((b, i) => {
    const meta = BUCKETS[b.key];
    return `<div class="usage-row">
      <span class="ic ${meta.icon}"></span>
      <div class="usage-main">
        <div class="usage-bar" data-w="${b.pct * 0.55}" data-tone="${i}"><span>${b.pct}%</span></div>
        <span class="usage-text">${num(b.count)} ${meta.label}</span>
      </div>
    </div>`;
  }).join('');
}

function heatmap(activity) {
  // activity is oldest -> newest; each step back shifts the window by four weeks
  const end = activity.length - heatOffset * 28;
  const window = activity.slice(Math.max(0, end - HEAT_WEEKS * 7), end);
  const first = new Date(`${window[0].date}T12:00:00`);
  const lead = (first.getDay() + 6) % 7;
  const cells = [...Array(lead).fill(null), ...window];
  const max = Math.max(1, ...window.map((d) => d.words));
  const weeks = [];
  for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
  let lastMonth = -1;
  const months = weeks.map((w) => {
    const day = w.find(Boolean);
    const m = day ? new Date(`${day.date}T12:00:00`).getMonth() : lastMonth;
    const label = m !== lastMonth && day ? new Date(`${day.date}T12:00:00`).toLocaleDateString('de-DE', { month: 'short' }) : '';
    lastMonth = m;
    return `<span>${label}</span>`;
  }).join('');
  const level = (w) => (w === 0 ? 0 : w < max * 0.25 ? 4 : w < max * 0.5 ? 3 : w < max * 0.75 ? 2 : 1);
  const grid = WEEKDAY_ROWS.map((label, row) => `
    <span class="heat-day">${label}</span>
    ${weeks.map((w) => {
      const d = w[row];
      if (!d) return '<i class="heat-cell empty"></i>';
      const dt = new Date(`${d.date}T12:00:00`).toLocaleDateString('de-DE', { day: 'numeric', month: 'short' });
      return `<i class="heat-cell l${level(d.words)}" title="${escapeHtml(dt)}: ${num(d.words)} Wörter"></i>`;
    }).join('')}`).join('');
  return `<div class="heatmap" data-weeks="${weeks.length}">
      <div class="heat-months"><button class="heat-nav" data-heat="1" aria-label="Früher"><span class="ic i-chevron-left"></span></button>${months}</div>
      <button class="heat-nav right" data-heat="-1" aria-label="Später" ${heatOffset ? '' : 'disabled'}><span class="ic i-chevron-right"></span></button>
      <div class="heat-grid">${grid}</div>
    </div>
    <div class="heat-legend"><span>Mehr</span><i class="heat-cell l1"></i><i class="heat-cell l2"></i><i class="heat-cell l3"></i><i class="heat-cell l4"></i><span>Weniger</span></div>`;
}

function dailyBars(daily) {
  const max = Math.max(1, ...daily.map((d) => d.words));
  const every = Math.ceil(daily.length / 8);
  return daily.map((d, i) => {
    const label = new Date(`${d.date}T12:00:00`).toLocaleDateString('de-DE', { day: 'numeric', month: 'short' });
    return `<div class="bar-col" title="${escapeHtml(label)}: ${num(d.words)} Wörter">
      <div class="bar" data-h="${(d.words / max) * 100}"></div><span>${i % every === 0 ? label : ''}</span></div>`;
  }).join('');
}

// ---- voice tab -------------------------------------------------------------------
async function renderVoice() {
  const v = await ctx.call('voice_profile');
  const body = root.querySelector('#ins-body');
  if (!v.unlocked) {
    const pct = Math.min(100, (v.words_total / v.unlock_at) * 100);
    body.innerHTML = `
      <article class="card voice-locked">
        <span class="lock-badge"><span class="ic i-lock"></span></span>
        <h2 class="serif">Dein Stimmprofil</h2>
        <p class="hint-text">Ab ${num(v.unlock_at)} Wörtern analysiert Murmel, wie du sprichst: deine Catchphrase, dein Lieblingswort,
          deine Peak-Zeit und welcher Sprechtyp du bist.</p>
        <div class="unlock-bar"><i data-w="${pct}"></i></div>
        <div class="unlock-meta"><span>${num(v.words_total)} / ${num(v.unlock_at)} Wörter</span><b>Noch ${num(v.remaining)} Wörter</b></div>
      </article>
      <div class="voice-preview" aria-hidden="true">
        ${['Catchphrase', 'Lieblingswort', 'Peak-Zeit', 'Sprechtyp'].map((t) => `<div class="card voice-ghost"><span class="label">${t}</span><b>••••••</b></div>`).join('')}
      </div>`;
    requestAnimationFrame(() => body.querySelectorAll('[data-w]').forEach((el) => { el.style.width = `${el.dataset.w}%`; }));
    return;
  }
  const peak = `${String(v.peak_hour).padStart(2, '0')}–${String((v.peak_hour + 1) % 24).padStart(2, '0')} Uhr`;
  const maxCount = v.top_words[0]?.count || 1;
  body.innerHTML = `
    <article class="card persona">
      <div><span class="label">Dein Sprechtyp</span>
        <h2 class="serif">${escapeHtml(v.persona.title)}</h2>
        <p>${escapeHtml(v.persona.text)}</p></div>
      <div class="persona-stats">
        <div><b>${num(v.wpm)}</b><span>WPM</span></div>
        <div><b>${num(v.words_total)}</b><span>Wörter</span></div>
        <div><b>${v.richness}%</b><span>Wortvielfalt <span class="info left" data-tip="Anteil verschiedener Wörter an allen Wörtern – je höher, desto abwechslungsreicher."><span class="ic i-info"></span></span></span></div>
      </div>
    </article>
    <div class="voice-grid">
      <article class="card voice-card quote-card">
        <span class="label"><span class="ic i-quote"></span>Catchphrase</span>
        <b class="serif">${v.catch_phrase ? `„${escapeHtml(v.catch_phrase)}“` : '—'}</b>
        <small>${v.catch_phrase ? `${num(v.catch_phrase_count)}× gesagt` : 'Noch keine wiederkehrende Phrase'}</small>
      </article>
      <article class="card voice-card">
        <span class="label"><span class="ic i-hash"></span>Lieblingswort</span>
        <b class="serif">${v.most_used_word ? escapeHtml(v.most_used_word) : '—'}</b>
        <small>${num(v.most_used_count)}× verwendet</small>
      </article>
      <article class="card voice-card">
        <span class="label"><span class="ic i-clock"></span>Peak-Zeit</span>
        <b class="serif">${peak}</b>
        <small>Aktivster Tag: ${escapeHtml(v.peak_weekday || '—')}</small>
      </article>
      <article class="card voice-card">
        <span class="label"><span class="ic i-monitor"></span>Lieblings-App</span>
        <b class="serif cap">${escapeHtml(v.favorite_app || '—')}</b>
        <small>Ø ${num(v.avg_words)} Wörter pro Diktat · Rekord ${num(v.longest)}</small>
      </article>
    </div>
    <article class="card top-words">
      <header><h2>Deine meistgenutzten Wörter</h2><span class="info left" data-tip="Ohne Füll- und Bindewörter wie „und“, „der“ oder „ich“."><span class="ic i-info"></span></span></header>
      <div class="word-cloud">${v.top_words.map((w) => `<span class="word" data-size="${Math.round((w.count / maxCount) * 4)}">${escapeHtml(w.word)}<small>${num(w.count)}</small></span>`).join('')}</div>
    </article>`;
}

// ---- customize -------------------------------------------------------------------
function openCustomize() {
  const st = ctx.settings;
  const { el, close } = ctx.modal(`
    <h3>Insights anpassen</h3>
    <div class="form-row">
      <div class="field"><label for="c-wpm">Dein Tipp-Tempo (WPM)</label>
        <input class="input" id="c-wpm" type="number" min="5" max="200" value="${st.typing_wpm}"/>
        <span class="hint-text">Basis für „Zeit gespart“ und den Tacho.</span></div>
      <div class="field"><label for="c-goal">Tagesziel (Wörter)</label>
        <input class="input" id="c-goal" type="number" min="50" max="50000" step="50" value="${st.daily_goal}"/></div>
    </div>
    <div class="modal-actions"><button class="btn btn-ghost" data-close>Abbrechen</button>
      <button class="btn btn-light" id="save">Speichern</button></div>`);
  el.querySelector('#save').addEventListener('click', async () => {
    const wpm = Number(el.querySelector('#c-wpm').value);
    const goal = Number(el.querySelector('#c-goal').value);
    if (!(wpm >= 5 && wpm <= 200) || !(goal >= 50 && goal <= 50000)) {
      ctx.toast('Bitte gültige Werte eingeben (Tempo 5–200, Ziel 50–50.000).', true);
      return;
    }
    try {
      await ctx.saveSettings({ typing_wpm: wpm, daily_goal: goal });
      close();
      load();
    } catch (err) {
      ctx.toast(err.message, true);
    }
  });
}
