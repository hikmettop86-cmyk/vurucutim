const { contextBridge, ipcRenderer } = require('electron');
const pkg = require('./package.json');

contextBridge.exposeInMainWorld('vt', {
  version: pkg.version,
  detectAll: () => ipcRenderer.invoke('vt:detect-all'),
  installMissing: () => ipcRenderer.invoke('vt:install-missing'),
  openExternal: (url) => ipcRenderer.invoke('vt:open-external', url),
  copyToClipboard: (text) => ipcRenderer.invoke('vt:copy-to-clipboard', text),
  openLogsFolder: () => ipcRenderer.invoke('vt:open-logs-folder'),
  finishWizard: (opts) => ipcRenderer.invoke('vt:finish-wizard', opts),
  getPreferences: () => ipcRenderer.invoke('vt:get-preferences'),
  setPreferences: (partial) => ipcRenderer.invoke('vt:set-preferences', partial),
  // Renderer MUST invoke the returned function to unsubscribe, or listeners leak across re-runs.
  onProgress: (cb) => {
    const listener = (_e, payload) => cb(payload);
    ipcRenderer.on('vt:install-progress', listener);
    return () => ipcRenderer.removeListener('vt:install-progress', listener);
  },
  // Update dialog
  getUpdateInfo: () => ipcRenderer.invoke('vt:get-update-info'),
  updateInstall: () => ipcRenderer.invoke('vt:update-install'),
  updatePostpone: () => ipcRenderer.invoke('vt:update-postpone'),
  // License window
  getMachineId: () => ipcRenderer.invoke('vt:get-machine-id'),
  activateLicense: (serial) => ipcRenderer.invoke('vt:activate-license', serial),
  licenseAccepted: () => ipcRenderer.invoke('vt:license-accepted'),
  licenseQuit: () => ipcRenderer.invoke('vt:license-quit'),
});
