const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('vt', {
  detectAll: () => ipcRenderer.invoke('vt:detect-all'),
  installMissing: () => ipcRenderer.invoke('vt:install-missing'),
  openExternal: (url) => ipcRenderer.invoke('vt:open-external', url),
  finishWizard: (opts) => ipcRenderer.invoke('vt:finish-wizard', opts),
  getPreferences: () => ipcRenderer.invoke('vt:get-preferences'),
  setPreferences: (partial) => ipcRenderer.invoke('vt:set-preferences', partial),
  onProgress: (cb) => {
    const listener = (_e, payload) => cb(payload);
    ipcRenderer.on('vt:install-progress', listener);
    return () => ipcRenderer.removeListener('vt:install-progress', listener);
  },
});
