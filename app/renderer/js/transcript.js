// Transcript rendering shared by the notes page and the session window.
import { escapeHtml } from './format.js';

const SPEAKER_LABEL = { you: 'Du', them: 'Gegenüber', system: 'Hinweis' };

export function clock(seconds) {
  const total = Math.max(0, Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
}

/** Consecutive segments of one speaker form a turn, shown as one group of chat bubbles. */
export function turnsOf(segments) {
  return segments.reduce((turns, s) => {
    const last = turns[turns.length - 1];
    if (last && last.speaker === s.speaker) last.segments.push(s);
    else turns.push({ speaker: s.speaker, segments: [s] });
    return turns;
  }, []);
}

function turnHtml(turn) {
  if (turn.speaker === 'system') {
    return turn.segments.map((s) => `<p class="turn-system"><span>${clock(s.start_s)}</span>${escapeHtml(s.text)}</p>`).join('');
  }
  const label = SPEAKER_LABEL[turn.speaker] ?? escapeHtml(turn.speaker);
  return `
    <div class="turn turn-${turn.speaker}">
      <span class="turn-label">${label} · ${clock(turn.segments[0].start_s)}</span>
      ${turn.segments.map((s) => `<p class="bubble">${escapeHtml(s.text)}</p>`).join('')}
    </div>`;
}

/** Segments arrive from two streams, so they are sorted by time before grouping. */
export function transcriptHtml(segments) {
  const ordered = [...segments].sort((a, b) => a.start_s - b.start_s);
  return turnsOf(ordered).map(turnHtml).join('');
}

// Provisional text of the speech that is still going on, one entry per speaker. The final segment replaces it.
const livePreview = new Map();

export function setLivePreview({ speaker, start_s: startS, text }) {
  if (text) livePreview.set(speaker, { startS, text });
  else livePreview.delete(speaker);
}

export function clearLivePreview(speaker) {
  livePreview.delete(speaker);
}

export function resetLivePreview() {
  livePreview.clear();
}

export function livePreviewHtml() {
  return [...livePreview].map(([speaker, { startS, text }]) => `
    <div class="turn turn-${speaker} turn-live">
      <span class="turn-label">${SPEAKER_LABEL[speaker] ?? escapeHtml(speaker)} · ${clock(startS)}</span>
      <p class="bubble">${escapeHtml(text)}</p>
    </div>`).join('');
}
