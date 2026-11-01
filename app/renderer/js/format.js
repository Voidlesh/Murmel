// Small formatting helpers shared by the overlay and the dashboard.
const KEY_LABELS = {
  'caps lock': 'Caps Lock', ctrl: 'Strg', 'left ctrl': 'Strg links', 'right ctrl': 'Strg rechts',
  windows: 'Win', win: 'Win', alt: 'Alt', 'right alt': 'Alt rechts', 'alt gr': 'Alt Gr',
  shift: 'Umschalt', space: 'Leertaste', 'scroll lock': 'Rollen', 'page down': 'Bild ↓',
};

/** @param {string} hotkey */
export function hotkeyLabel(hotkey = '') {
  return hotkey
    .split('+')
    .map((k) => KEY_LABELS[k.trim()] || k.trim().replace(/^f(\d+)$/, 'F$1').replace(/^./, (c) => c.toUpperCase()))
    .join(' + ');
}

/** @param {string} s */
export function escapeHtml(s = '') {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

const nf = new Intl.NumberFormat('de-DE');
/** @param {number} n */
export const num = (n) => nf.format(Math.round(n || 0));

/** @param {number} ts unix seconds */
export function timeOfDay(ts) {
  return new Date(ts * 1000).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

/** @param {number} ts unix seconds */
export function dayLabel(ts) {
  const d = new Date(ts * 1000);
  const today = new Date();
  const yesterday = new Date(Date.now() - 864e5);
  if (d.toDateString() === today.toDateString()) return 'Heute';
  if (d.toDateString() === yesterday.toDateString()) return 'Gestern';
  return d.toLocaleDateString('de-DE', { weekday: 'long', day: 'numeric', month: 'long' });
}

/** @param {number} minutes */
export function duration(minutes) {
  if (minutes < 1) return `${Math.round(minutes * 60)} s`;
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const h = Math.floor(minutes / 60);
  return `${h} h ${Math.round(minutes % 60)} min`;
}
