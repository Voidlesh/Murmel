// Transcript rendering shared by the notes page and the session window.
import { escapeHtml } from './format.js';

const SPEAKER_LABEL = { you: 'Du', them: 'Gegenüber' };

export function clock(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
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
