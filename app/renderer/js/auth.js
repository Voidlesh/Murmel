import { call } from './api.js';
import { escapeHtml } from './format.js';

let root;
let onDone;
let mode = 'login';
let accounts = [];

/**
 * Shows the sign-in / sign-up screen until an account is active.
 * @param {HTMLElement} el
 * @param {{ accounts: Array<{name: string, email: string}> }} status
 * @param {(result: {account: object, settings: object}) => void} done
 */
export function showAuth(el, status, done) {
  root = el;
  onDone = done;
  accounts = status.accounts || [];
  mode = accounts.length ? 'login' : 'register';
  root.hidden = false;
  document.body.classList.add('auth-open');
  render();
}

export function hideAuth() {
  if (!root) return;
  root.hidden = true;
  root.innerHTML = '';
  document.body.classList.remove('auth-open');
}

function render() {
  const isLogin = mode === 'login';
  root.innerHTML = `
    <div class="auth-art" aria-hidden="true">
      <div class="auth-brand"><span class="brand-mark"><i></i><i></i><i></i><i></i></span>Murmel</div>
      <div class="auth-quote">
        <p class="serif">Sprich, als würdest du <em>tippen</em> –<br/>nur viermal so schnell.</p>
        <span>Lokal auf deinem PC · keine Cloud · kostenlos</span>
      </div>
      <div class="auth-wave">${Array.from({ length: 28 }, (_, i) => `<i data-i="${i}"></i>`).join('')}</div>
    </div>
    <div class="auth-panel">
      <form class="auth-card" id="auth-form" autocomplete="on" novalidate>
        <h1>${isLogin ? 'Willkommen zurück' : 'Account erstellen'}</h1>
        <p class="hint-text">${isLogin
          ? 'Melde dich an, um deinen Verlauf, dein Wörterbuch und deine Stats zu laden.'
          : 'Dein Account bleibt auf diesem PC. Verlauf, Wörterbuch, Snippets und Stats werden darin gespeichert.'}</p>
        ${isLogin && accounts.length ? `
          <div class="auth-accounts">${accounts.map((a) => `
            <button type="button" class="auth-account" data-login="${escapeHtml(a.email)}">
              <span class="avatar">${escapeHtml(initials(a.name))}</span>
              <span><b>${escapeHtml(a.name)}</b><small>${escapeHtml(a.email)}</small></span>
            </button>`).join('')}</div>` : ''}
        ${isLogin ? '' : `
          <div class="field"><label for="au-name">Name</label>
            <input class="input" id="au-name" name="name" autocomplete="nickname" maxlength="40" required/></div>`}
        <div class="field"><label for="au-login">${isLogin ? 'E-Mail oder Name' : 'E-Mail'}</label>
          <input class="input" id="au-login" name="${isLogin ? 'username' : 'email'}" type="${isLogin ? 'text' : 'email'}"
            autocomplete="${isLogin ? 'username' : 'email'}" maxlength="120" required/></div>
        <div class="field"><label for="au-pw">Passwort</label>
          <div class="pw-wrap"><input class="input" id="au-pw" name="password" type="password"
            autocomplete="${isLogin ? 'current-password' : 'new-password'}" minlength="6" maxlength="200" required/>
          <button type="button" class="icon-btn" id="au-eye" aria-label="Passwort anzeigen"><span class="ic i-eye"></span></button></div>
          ${isLogin ? '' : '<span class="hint-text">Mindestens 6 Zeichen.</span>'}</div>
        ${isLogin ? `<label class="remember"><input type="checkbox" id="au-remember" checked/> Angemeldet bleiben</label>` : ''}
        <p class="auth-error" id="au-error" role="alert"></p>
        <button class="btn btn-light auth-submit" type="submit" id="au-submit">${isLogin ? 'Anmelden' : 'Account erstellen'}</button>
        <p class="auth-switch">${isLogin ? 'Noch keinen Account?' : 'Schon einen Account?'}
          <button type="button" id="au-switch">${isLogin ? 'Account erstellen' : 'Anmelden'}</button></p>
      </form>
    </div>`;

  const form = root.querySelector('#auth-form');
  form.addEventListener('submit', submit);
  root.querySelector('#au-switch').addEventListener('click', () => { mode = isLogin ? 'register' : 'login'; render(); });
  root.querySelector('#au-eye').addEventListener('click', () => {
    const pw = root.querySelector('#au-pw');
    pw.type = pw.type === 'password' ? 'text' : 'password';
    root.querySelector('#au-eye .ic').className = `ic ${pw.type === 'password' ? 'i-eye' : 'i-eye-off'}`;
  });
  root.querySelectorAll('[data-login]').forEach((b) => b.addEventListener('click', () => {
    root.querySelector('#au-login').value = b.dataset.login;
    root.querySelector('#au-pw').focus();
  }));
  root.querySelector(isLogin && accounts.length === 1 ? '#au-pw' : 'input').focus();
  if (isLogin && accounts.length === 1) root.querySelector('#au-login').value = accounts[0].email;
}

async function submit(e) {
  e.preventDefault();
  const error = root.querySelector('#au-error');
  const button = root.querySelector('#au-submit');
  const login = root.querySelector('#au-login').value.trim();
  const password = root.querySelector('#au-pw').value;
  error.textContent = '';
  if (!login || !password) { error.textContent = 'Bitte fülle alle Felder aus.'; return; }
  button.disabled = true;
  try {
    const result = mode === 'login'
      ? await call('auth_login', { login, password, remember: root.querySelector('#au-remember').checked })
      : await call('auth_register', { name: root.querySelector('#au-name').value.trim(), email: login, password });
    hideAuth();
    onDone(result);
  } catch (err) {
    error.textContent = err.message;
    button.disabled = false;
  }
}

export function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((p) => p[0] || '').join('').toUpperCase() || '?';
}
