const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('murmel', {
  minimize: () => ipcRenderer.send('window:minimize'),
  maximize: () => ipcRenderer.send('window:maximize'),
  close: () => ipcRenderer.send('window:close'),
  showMain: () => ipcRenderer.send('app:show'),
  quit: () => ipcRenderer.send('app:quit'),
  setOverlayInteractive: (on) => ipcRenderer.send('overlay:interactive', Boolean(on)),
  getOverlayDock: () => ipcRenderer.invoke('overlay:get-dock'),
  overlayDragStart: () => ipcRenderer.invoke('overlay:drag-start'),
  overlayDrop: (dock) => ipcRenderer.invoke('overlay:drop', dock),
  copyToClipboard: (text) => ipcRenderer.invoke('overlay:copy', String(text)),
  onOverlayDock: (cb) => ipcRenderer.on('overlay:dock', (_e, dock) => cb(dock)),
  getAutostart: () => ipcRenderer.invoke('app:get-autostart'),
  setAutostart: (on) => ipcRenderer.invoke('app:set-autostart', Boolean(on)),
  openDataDir: () => ipcRenderer.invoke('app:open-data-dir'),
  onMaximized: (cb) => ipcRenderer.on('window:maximized', (_e, v) => cb(v)),
});
