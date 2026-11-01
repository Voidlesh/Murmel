import { call, on } from './api.js';
import { playStart, playStop, playError } from './sounds.js';
import { hotkeyLabel } from './format.js';

// Dictation waveform of the reference: 10 bars, no per-bar gain.
const BAR_COUNT = 10;
const bars = [];
const SPINNER_BARS = 8;
const LEVEL_GAIN = 6.5;         // audio level 0..1 -> bar scale on top of the resting scale
const REST_SCALE = 1.6;        // pauses keep a small breathing wave instead of dropping flat
const PITCH_MIX = 0.6;         // share of the per-band level vs overall loudness in each bar
const SMOOTHING = 0.85;        // per 60 fps frame, one-pole low-pass like the reference
const MIC_ACTIVE_LEVEL = 0.04;
const TOOLTIP_MS = 2200;
const DRAG_THRESHOLD_PX = 6;
const CLICK_AFTER_DRAG_MS = 250;
const ZONE_EDGE_OFFSET = 32;   // pill centre distance from the screen edge when docked

const bubble = document.getElementById('bubble');
const hotArea = document.getElementById('hot-area');
const waveform = document.getElementById('waveform');
const spinner = document.getElementById('spinner');
const tooltip = document.getElementById('tooltip');
const copyPanel = document.getElementById('copy-panel');
const copyText = document.getElementById('copy-text');
const copyBtn = document.getElementById('copy-btn');
const COPY_DONE_MS = 900;
const COPY_CLOSE_MS = 280;  // matches the collapse transition in overlay.css

let engineState = 'loading';
let handsFree = false;
let hovered = false;
let soundsOn = true;
let hotkey = 'caps lock';
const targets = new Array(BAR_COUNT).fill(0);   // per-bar level 0..1 (low -> high pitch)
const scales = new Array(BAR_COUNT).fill(0);
const shown = new Array(BAR_COUNT).fill('');
let tooltipTimer = null;

// Bars bulge in the middle; animation delays mirror around the centre.
const half = Math.ceil(BAR_COUNT / 2);
for (let p = 0; p < BAR_COUNT; p++) {
  const bar = document.createElement('i');
  bar.className = 'wbar';
  const h = Math.abs((BAR_COUNT - 1) / 2 - p);
  bar.style.setProperty('--bar-height-scale', Math.max(0, 1 - h * h * (1 / 48)).toFixed(3));
  bar.style.animationDelay = `${0.1 * (p < half ? p : p - BAR_COUNT)}s`;
  waveform.appendChild(bar);
  bars.push(bar);
}
for (let a = 0; a < SPINNER_BARS; a++) {
  const bar = document.createElement('i');
  bar.style.transform = `rotate(${45 * a}deg) translate(0, -6px)`;
  bar.style.animationDelay = `${-0.1375 * (SPINNER_BARS - 1 - a)}s`;
  spinner.appendChild(bar);
}

function visualState() {
  if (engineState === 'recording') return handsFree ? 'popo' : 'ptt';
  if (engineState === 'processing') return 'processing';
  if (engineState === 'error') return 'error';
  if (engineState === 'loading') return 'loading';
  return hovered ? 'ready' : 'resting';
}

function render() {
  const state = visualState();
  bubble.dataset.state = state;
  bubble.classList.toggle('listening', state === 'ptt' || state === 'popo');
  if (state !== 'ptt' && state !== 'popo') {
    targets.fill(0);
    bubble.classList.remove('mic-active');
  }
}

let lastFrame = 0;
function frame(now) {
  const dt = Math.min(Math.max(now - lastFrame, 1), 100);
  lastFrame = now;
  const keep = SMOOTHING ** (dt / (1000 / 60));
  for (let i = 0; i < BAR_COUNT; i++) {
    scales[i] = scales[i] * keep + targets[i] * LEVEL_GAIN * (1 - keep);
    const value = Math.max(REST_SCALE, scales[i]).toFixed(2);
    if (value !== shown[i]) {
      shown[i] = value;
      bars[i].style.setProperty('--bar-audio-scale', value);
    }
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);

function showTooltip(html, sticky = false, rich = false) {
  tooltip.innerHTML = html;
  tooltip.classList.toggle('card', rich);
  tooltip.classList.add('show');
  clearTimeout(tooltipTimer);
  if (!sticky) tooltipTimer = setTimeout(() => tooltip.classList.remove('show'), TOOLTIP_MS);
}
const hideTooltip = () => tooltip.classList.remove('show');
const keyHtml = () => `<span class="key">${hotkeyLabel(hotkey).replace(/[<>&]/g, '')}</span>`;

// ---- copy panel: a dictation that could not be pasted (no text field focused) ----
function showCopyPanel(text) {
  copyText.textContent = text;
  copyBtn.textContent = 'Kopieren';
  copyPanel.hidden = false;
  // two frames: the panel must be laid out in its collapsed state before the open class starts the transition
  requestAnimationFrame(() => requestAnimationFrame(() => copyPanel.classList.add('open')));
}

function hideCopyPanel() {
  copyPanel.classList.remove('open');
  window.murmel.setOverlayInteractive(false);
  setTimeout(() => { if (!copyPanel.classList.contains('open')) copyPanel.hidden = true; }, COPY_CLOSE_MS);
}

on('copy_panel', (msg) => showCopyPanel(msg.text));
copyPanel.addEventListener('mouseenter', () => window.murmel.setOverlayInteractive(true));
copyPanel.addEventListener('mouseleave', () => window.murmel.setOverlayInteractive(false));
document.getElementById('copy-close').addEventListener('click', hideCopyPanel);
copyBtn.addEventListener('click', async () => {
  try {
    await window.murmel.copyToClipboard(copyText.textContent);
    copyBtn.textContent = 'Kopiert';
    setTimeout(hideCopyPanel, COPY_DONE_MS);
  } catch (err) {
    copyBtn.textContent = 'Fehlgeschlagen';
    showTooltip(err.message);
  }
});

on('state', (msg) => {
  const prev = engineState;
  engineState = msg.state;
  handsFree = Boolean(msg.hands_free);
  soundsOn = msg.sounds;
  hotkey = msg.hotkey;
  render();
  if (engineState === 'recording') {
    hideTooltip();
    if (copyPanel.classList.contains('open')) hideCopyPanel();
  }
  if (soundsOn && prev !== 'recording' && engineState === 'recording') playStart();
  if (soundsOn && prev === 'recording' && engineState !== 'recording' && msg.detail !== 'Abgebrochen') playStop();
  if (engineState === 'error') {
    if (soundsOn) playError();
    showTooltip(msg.detail || 'Fehler');
  } else if (engineState === 'idle' && msg.detail.startsWith('Nichts')) {
    showTooltip(msg.detail);
  }
});
// Low pitch sits in the middle, higher pitch spreads outwards; both sides are identical.
// Blending in the overall loudness keeps the centre the tallest even for a dark voice.
function mirrorBands(bands, overall) {
  const pairs = BAR_COUNT / 2;
  for (let d = 0; d < pairs; d++) {
    const pair = (bands[2 * d] + bands[2 * d + 1]) / 2;
    const level = PITCH_MIX * pair + (1 - PITCH_MIX) * overall;
    targets[pairs - 1 - d] = level;
    targets[pairs + d] = level;
  }
}
on('level', (msg) => {
  mirrorBands(msg.bands, msg.value);
  bubble.classList.toggle('mic-active', msg.value > MIC_ACTIVE_LEVEL);
});
on('notice', (msg) => showTooltip(msg.text));
on('connection', (up) => { if (!up) { engineState = 'loading'; render(); } });

// The window ignores the mouse except over the hot area (pill + padding).
hotArea.addEventListener('mouseenter', () => {
  window.murmel.setOverlayInteractive(true);
  hovered = true;
  hotArea.classList.add('hovered');
  render();
  if (engineState === 'idle') showTooltip(`Halte ${keyHtml()}`, true);
});
hotArea.addEventListener('mouseleave', () => {
  window.murmel.setOverlayInteractive(false);
  hovered = false;
  hotArea.classList.remove('hovered');
  render();
  if (engineState === 'idle') hideTooltip();
});
bubble.addEventListener('click', (e) => {
  if (e.target.closest('.bar-btn') || performance.now() - lastDragEnd < CLICK_AFTER_DRAG_MS) return;
  if (engineState === 'idle') {
    hideTooltip();
    call('toggle').catch((err) => showTooltip(err.message));
  } else if (engineState === 'error') {
    window.murmel.showMain();
  }
});
document.getElementById('btn-cancel').addEventListener('click', () => call('cancel'));
document.getElementById('btn-stop').addEventListener('click', () => call('toggle'));

// ---- notes: start/stop a long session from the island ---------------------------------------
const notesBtn = document.getElementById('btn-notes');
let sessionLive = false;
let liveSessionId = null;

function notesTipHtml() {
  return sessionLive
    ? '<b>Live-Transkript öffnen</b><span>Zeigt Transkript und Notizen der laufenden Aufnahme</span>'
    : '<b>Notizen-Aufnahme starten</b><span>Transkript, Notizen und Aufgaben für jede Aufnahme</span>';
}

function renderNotes() {
  notesBtn.classList.toggle('live', sessionLive);
  notesBtn.setAttribute('aria-label', sessionLive ? 'Live-Transkript öffnen' : 'Notizen-Aufnahme starten');
}

on('session_status', (msg) => {
  sessionLive = msg.session?.status === 'recording';
  if (sessionLive) liveSessionId = msg.session.id;
  renderNotes();
});
notesBtn.addEventListener('mouseenter', () => {
  window.murmel.setOverlayInteractive(true);
  showTooltip(notesTipHtml(), true, true);
});
notesBtn.addEventListener('mouseleave', () => {
  if (!hovered) window.murmel.setOverlayInteractive(false);
  hideTooltip();
});
notesBtn.addEventListener('click', async () => {
  if (sessionLive) {
    window.murmel.showSession(liveSessionId); // a running session opens its live window instead
    hideTooltip();
    return;
  }
  try {
    await call('session_start', {});
    hideTooltip();
  } catch (err) {
    showTooltip(err.message);
  }
});
renderNotes();

// ---- docking: drag the pill to the bottom, top, left or right edge ---------------------------------
const dragLayer = document.getElementById('drag-layer');
const dragger = document.getElementById('dragger');
const zones = [...dragLayer.querySelectorAll('.zone')];
let lastDragEnd = 0;
let drag = null; // { startX, startY, phase: 'pending' | 'starting' | 'active', x, y, released }

function applyDock(dock) {
  document.body.dataset.dock = dock;
  document.body.dataset.axis = dock === 'left' || dock === 'right' ? 'v' : 'h';
}

function zoneCenters() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  return { top: [w / 2, ZONE_EDGE_OFFSET], bottom: [w / 2, h - ZONE_EDGE_OFFSET], left: [ZONE_EDGE_OFFSET, h / 2], right: [w - ZONE_EDGE_OFFSET, h / 2] };
}

function nearestDock(x, y) {
  const centers = zoneCenters();
  return Object.keys(centers).reduce((best, key) =>
    (Math.hypot(x - centers[key][0], y - centers[key][1]) < Math.hypot(x - centers[best][0], y - centers[best][1]) ? key : best));
}

function paintDrag() {
  const centers = zoneCenters();
  const active = nearestDock(drag.x, drag.y);
  zones.forEach((zone) => {
    const [cx, cy] = centers[zone.dataset.dock];
    zone.style.left = `${cx}px`;
    zone.style.top = `${cy}px`;
    zone.classList.toggle('active', zone.dataset.dock === active);
  });
  dragger.style.left = `${drag.x}px`;
  dragger.style.top = `${drag.y}px`;
}

async function finishDrag(dockOverride) {
  const target = dockOverride ?? nearestDock(drag.x, drag.y);
  drag = null;
  lastDragEnd = performance.now();
  document.body.classList.remove('dragging');
  window.murmel.setOverlayInteractive(false);
  hovered = false;
  applyDock(await window.murmel.overlayDrop(target));
  render();
}

async function beginDrag() {
  drag.phase = 'starting';
  hideTooltip();
  await window.murmel.overlayDragStart();
  if (!drag) return;
  if (drag.released) { finishDrag(document.body.dataset.dock); return; }
  drag.phase = 'active';
  document.body.classList.add('dragging');
  paintDrag();
}

bubble.addEventListener('pointerdown', (e) => {
  if (e.button !== 0 || e.target.closest('.bar-btn')) return;
  if (engineState === 'recording' || engineState === 'processing') return;
  drag = { startX: e.screenX, startY: e.screenY, phase: 'pending', x: 0, y: 0, released: false };
});
window.addEventListener('pointermove', (e) => {
  if (!drag) return;
  if (drag.phase === 'pending' && Math.hypot(e.screenX - drag.startX, e.screenY - drag.startY) > DRAG_THRESHOLD_PX) beginDrag();
  if (drag?.phase === 'active') {
    drag.x = e.clientX;
    drag.y = e.clientY;
    paintDrag();
  }
});
window.addEventListener('pointerup', () => {
  if (!drag) return;
  if (drag.phase === 'pending') drag = null;               // plain click, handled by the click listener
  else if (drag.phase === 'starting') drag.released = true;
  else finishDrag();
});

window.murmel.getOverlayDock().then(applyDock);
window.murmel.onOverlayDock(applyDock);
render();
