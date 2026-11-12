// WebSocket client for the Murmel engine with auto-reconnect and request/response.
const URL = 'ws://127.0.0.1:47821';
const RECONNECT_MS = 1000;
const REQUEST_TIMEOUT_MS = 60000;
// stopping a session waits until the last audio is transcribed, and an import decodes the whole file
const SLOW_METHODS = { session_stop: 15 * 60000, session_import: 10 * 60000 };

let ws = null;
let nextId = 1;
const pending = new Map();
const listeners = new Map();
let queue = [];

function emit(type, payload) {
  (listeners.get(type) || []).forEach((cb) => cb(payload));
}

function connect() {
  ws = new WebSocket(URL);
  ws.onopen = () => {
    emit('connection', true);
    queue.forEach((msg) => ws.send(msg));
    queue = [];
  };
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject, timer } = pending.get(msg.id);
      clearTimeout(timer);
      pending.delete(msg.id);
      if ('error' in msg) reject(new Error(msg.error));
      else resolve(msg.result);
      return;
    }
    if (msg.type) emit(msg.type, msg);
  };
  ws.onclose = () => {
    emit('connection', false);
    setTimeout(connect, RECONNECT_MS);
  };
  ws.onerror = () => ws.close();
}

/** @param {string} type @param {(msg: any) => void} cb */
export function on(type, cb) {
  listeners.set(type, [...(listeners.get(type) || []), cb]);
}

/** @param {string} method @param {Record<string, unknown>} [params] @returns {Promise<any>} */
export function call(method, params = {}) {
  const id = nextId++;
  const msg = JSON.stringify({ id, method, params });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Zeitüberschreitung: ${method}`));
    }, SLOW_METHODS[method] ?? REQUEST_TIMEOUT_MS);
    pending.set(id, { resolve, reject, timer });
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(msg);
    else queue.push(msg);
  });
}

connect();
