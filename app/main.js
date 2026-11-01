const { app, BrowserWindow, Tray, Menu, ipcMain, screen, nativeImage, shell, clipboard } = require('electron');
const { spawn } = require('child_process');
const net = require('net');
const path = require('path');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..');
const ENGINE_PORT = 47821;
const OVERLAY_SIZES = {
  horizontal: { width: 420, height: 260 }, // room for the copy panel above the pill
  vertical: { width: 240, height: 420 }, // room for the pill plus the tooltip beside it
};
const OVERLAY_EDGE_GAP = 2; // pill sits ~16px from the screen edge like the reference
const DOCKS = ['bottom', 'top', 'left', 'right'];
const ICON_PATH = path.join(__dirname, 'assets', 'icon.png');

let mainWindow = null;
let overlayWindow = null;
let tray = null;
let engineProc = null;
let quitting = false;
let dock = 'bottom';

// keep Electron's cache out of the engine's data folder (%APPDATA%/Murmel holds the accounts)
app.setPath('userData', path.join(app.getPath('appData'), 'Murmel', 'ui'));

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', showMain);
  app.whenReady().then(start);
}

function portOpen(port) {
  return new Promise((resolve) => {
    const sock = net.connect({ port, host: '127.0.0.1' });
    sock.once('connect', () => { sock.destroy(); resolve(true); });
    sock.once('error', () => resolve(false));
  });
}

// the installed app ships the engine as a PyInstaller bundle; in dev mode it runs from the project venv
function engineCommand() {
  if (app.isPackaged) {
    const exe = path.join(process.resourcesPath, 'engine', 'murmel-engine.exe');
    return { command: exe, args: [], cwd: path.dirname(exe) };
  }
  return { command: path.join(ROOT, '.venv', 'Scripts', 'pythonw.exe'), args: ['-m', 'engine'], cwd: ROOT };
}

async function startEngine() {
  if (await portOpen(ENGINE_PORT)) return; // engine already running (dev mode)
  const { command, args, cwd } = engineCommand();
  if (!fs.existsSync(command)) {
    console.error('Engine fehlt:', command);
    return;
  }
  engineProc = spawn(command, args, { cwd, windowsHide: true, stdio: 'ignore' });
  engineProc.on('exit', (code) => {
    engineProc = null;
    if (!quitting) console.error('Engine beendet mit Code', code);
  });
}

function createMain() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1040,
    minHeight: 680,
    frame: false,
    backgroundColor: '#161616',
    icon: ICON_PATH,
    show: !process.argv.includes('--hidden'),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  // --page=insights --tab=voice --theme=light open the window at a specific view
  const query = {};
  for (const key of ['page', 'tab', 'theme']) {
    const arg = process.argv.find((a) => a.startsWith(`--${key}=`));
    if (arg) query[key] = arg.slice(key.length + 3);
  }
  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'), { query });
  mainWindow.on('close', (e) => {
    if (!quitting) { e.preventDefault(); mainWindow.hide(); }
  });
  mainWindow.on('maximize', () => mainWindow.webContents.send('window:maximized', true));
  mainWindow.on('unmaximize', () => mainWindow.webContents.send('window:maximized', false));
  mainWindow.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
}

const dockFile = () => path.join(app.getPath('userData'), 'overlay.json');

function loadDock() {
  try {
    const saved = JSON.parse(fs.readFileSync(dockFile(), 'utf8')).dock;
    if (DOCKS.includes(saved)) dock = saved;
  } catch { /* first start: bottom */ }
}

function saveDock() {
  try { fs.writeFileSync(dockFile(), JSON.stringify({ dock })); } catch (err) { console.error('Dock nicht speicherbar', err); }
}

const overlaySize = () => OVERLAY_SIZES[dock === 'left' || dock === 'right' ? 'vertical' : 'horizontal'];

function placeOverlay() {
  const area = screen.getPrimaryDisplay().workArea;
  const size = overlaySize();
  const centerX = Math.round(area.x + (area.width - size.width) / 2);
  const centerY = Math.round(area.y + (area.height - size.height) / 2);
  const origin = {
    bottom: { x: centerX, y: area.y + area.height - size.height - OVERLAY_EDGE_GAP },
    top: { x: centerX, y: area.y + OVERLAY_EDGE_GAP },
    left: { x: area.x + OVERLAY_EDGE_GAP, y: centerY },
    right: { x: area.x + area.width - size.width - OVERLAY_EDGE_GAP, y: centerY },
  }[dock];
  overlayWindow.setBounds({ ...origin, ...size });
}

function createOverlay() {
  loadDock();
  overlayWindow = new BrowserWindow({
    ...overlaySize(),
    frame: false,
    transparent: true,
    resizable: false,
    movable: false,
    focusable: false,
    skipTaskbar: true,
    hasShadow: false,
    alwaysOnTop: true,
    show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
  });
  overlayWindow.setAlwaysOnTop(true, 'screen-saver');
  overlayWindow.setIgnoreMouseEvents(true, { forward: true });
  overlayWindow.loadFile(path.join(__dirname, 'renderer', 'overlay.html'));
  overlayWindow.once('ready-to-show', () => { placeOverlay(); overlayWindow.showInactive(); });
  screen.on('display-metrics-changed', placeOverlay);
  screen.on('display-added', placeOverlay);
  screen.on('display-removed', placeOverlay);
}

function createTray() {
  tray = new Tray(nativeImage.createFromPath(ICON_PATH).resize({ width: 16, height: 16 }));
  tray.setToolTip('Murmel');
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: 'Murmel öffnen', click: showMain },
    { type: 'separator' },
    { label: 'Beenden', click: () => { quitting = true; app.quit(); } },
  ]));
  tray.on('click', showMain);
}

let sessionWindow = null;

function showSession(id) {
  if (!sessionWindow) {
    sessionWindow = new BrowserWindow({
      width: 460,
      height: 720,
      minWidth: 380,
      minHeight: 460,
      frame: false,
      backgroundColor: '#161616',
      icon: ICON_PATH,
      show: false,
      webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, sandbox: true },
    });
    sessionWindow.loadFile(path.join(__dirname, 'renderer', 'session.html'), { query: { session: String(id) } });
    sessionWindow.on('close', (e) => {
      if (!quitting) { e.preventDefault(); sessionWindow.hide(); }
    });
    sessionWindow.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  } else {
    sessionWindow.webContents.send('session:open', id);
  }
  if (sessionWindow.isMinimized()) sessionWindow.restore();
  sessionWindow.show();
  sessionWindow.focus();
}

function showMain() {
  if (!mainWindow) return;
  if (mainWindow.isMinimized()) mainWindow.restore();
  mainWindow.show();
  mainWindow.focus();
}

function registerIpc() {
  ipcMain.on('window:minimize', () => mainWindow?.minimize());
  ipcMain.on('window:maximize', () => (mainWindow?.isMaximized() ? mainWindow.unmaximize() : mainWindow?.maximize()));
  ipcMain.on('window:close', () => mainWindow?.hide());
  ipcMain.on('app:show', showMain);
  ipcMain.on('session:show', (_e, id) => showSession(Number(id)));
  ipcMain.on('session:close', () => sessionWindow?.hide());
  ipcMain.on('app:quit', () => { quitting = true; app.quit(); });
  ipcMain.on('overlay:interactive', (_e, interactive) => {
    overlayWindow?.setIgnoreMouseEvents(!interactive, { forward: true });
  });
  ipcMain.handle('overlay:get-dock', () => dock);
  ipcMain.handle('overlay:copy', (_e, text) => clipboard.writeText(text));
  // while dragging, the transparent window covers the whole work area so the pill can follow the cursor
  ipcMain.handle('overlay:drag-start', () => {
    overlayWindow?.setBounds(screen.getPrimaryDisplay().workArea);
    overlayWindow?.setIgnoreMouseEvents(false);
  });
  ipcMain.handle('overlay:drop', (_e, target) => {
    if (DOCKS.includes(target)) { dock = target; saveDock(); }
    if (!overlayWindow) return dock;
    placeOverlay();
    overlayWindow.setIgnoreMouseEvents(true, { forward: true });
    overlayWindow.webContents.send('overlay:dock', dock);
    return dock;
  });
  ipcMain.handle('app:get-autostart', () => app.getLoginItemSettings({
    args: app.isPackaged ? ['--hidden'] : [app.getAppPath(), '--hidden'],
  }).openAtLogin);
  ipcMain.handle('app:set-autostart', (_e, enabled) => {
    // unpackaged electron.exe needs the app folder, otherwise it would open the default Electron app
    const args = app.isPackaged ? ['--hidden'] : [app.getAppPath(), '--hidden'];
    app.setLoginItemSettings({ openAtLogin: Boolean(enabled), args });
    return app.getLoginItemSettings({ args }).openAtLogin; // same args as the write, or Windows reports it as off
  });
  ipcMain.handle('app:open-data-dir', () => shell.openPath(path.join(app.getPath('appData'), 'Murmel')));
}

async function start() {
  app.setAppUserModelId('dev.murmel.app');
  registerIpc();
  await startEngine();
  createMain();
  createOverlay();
  createTray();
}

app.on('before-quit', () => {
  quitting = true;
  // the venv's pythonw.exe is a launcher that spawns the real interpreter, so kill the whole tree
  if (engineProc) spawn('taskkill', ['/pid', String(engineProc.pid), '/T', '/F'], { windowsHide: true });
});
app.on('window-all-closed', () => { /* stay in tray */ });
