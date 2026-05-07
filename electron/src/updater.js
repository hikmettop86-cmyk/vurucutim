const { autoUpdater } = require('electron-updater');
const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('node:path');
const log = require('./logger');
const prefs = require('./preferences');

autoUpdater.logger = log;
autoUpdater.autoDownload = true;
autoUpdater.autoInstallOnAppQuit = false;   // user must explicitly accept

let _ctx = null;
let _manualTriggered = false;
let _updateState = 'idle';   // idle | checking | available | downloading | downloaded | error
let _pendingInfo = null;
let _dialogWin = null;
let _ipcRegistered = false;

function init(ctx) {
  _ctx = ctx;
  registerIpcOnce();

  autoUpdater.on('checking-for-update', () => {
    _updateState = 'checking';
    log.info('updater: checking');
  });
  autoUpdater.on('update-not-available', (info) => {
    _updateState = 'idle';
    log.info('updater: up to date', info?.version);
    if (_manualTriggered) {
      const { dialog } = require('electron');
      try {
        dialog.showMessageBox({
          type: 'info',
          title: 'Güncelleme yok',
          message: 'Güncelleme bulunamadı.',
          detail: `Mevcut sürüm: v${app.getVersion()}`,
        });
      } catch (_) {}
    }
  });
  autoUpdater.on('update-available', (info) => {
    _updateState = 'available';
    log.info('updater: available', info.version);
  });
  autoUpdater.on('download-progress', (p) => {
    _updateState = 'downloading';
    log.info(`updater: %${Math.round(p.percent)}`);
  });
  autoUpdater.on('update-downloaded', (info) => {
    _updateState = 'downloaded';
    log.info('updater: downloaded', info.version);
    _pendingInfo = info;
    openDialog();
  });
  autoUpdater.on('error', (err) => {
    _updateState = 'error';
    log.error('updater: error', err);
    if (_manualTriggered) {
      const { dialog } = require('electron');
      try { dialog.showErrorBox('Güncelleme hatası', err.message || String(err)); } catch (_) {}
    }
  });
}

function registerIpcOnce() {
  if (_ipcRegistered) return;
  _ipcRegistered = true;

  ipcMain.handle('vt:get-update-info', () => ({
    currentVersion: app.getVersion(),
    newVersion: _pendingInfo?.version || '?',
    releaseNotes: _pendingInfo?.releaseNotes || '',
  }));

  ipcMain.handle('vt:update-install', async () => {
    // CRITICAL: signal app-wide that this is a real quit (not "hide to tray")
    // and tear down resources so NSIS can replace the .exe without "cannot be closed".
    app.isQuitting = true;
    if (_ctx?.beforeQuit) {
      try { await _ctx.beforeQuit(); } catch (e) { log.warn('updater beforeQuit failed:', e.message); }
    }
    // Destroy all windows (close handlers preventDefault otherwise — they hide to tray)
    try {
      for (const w of BrowserWindow.getAllWindows()) {
        try { w.destroy(); } catch (_) {}
      }
    } catch (_) {}
    // Tear down tray icon so the process can fully exit
    if (_ctx?.tray?.destroy) {
      try { _ctx.tray.destroy(); } catch (_) {}
    }
    autoUpdater.quitAndInstall(false, true);
  });

  ipcMain.handle('vt:update-postpone', () => {
    if (_dialogWin) { try { _dialogWin.close(); } catch (_) {} }
  });
}

function openDialog() {
  if (_dialogWin) {
    try { _dialogWin.show(); _dialogWin.focus(); return; } catch (_) {}
  }
  _dialogWin = new BrowserWindow({
    width: 460,
    height: 320,
    resizable: false,
    minimizable: false,
    maximizable: false,
    fullscreenable: false,
    title: 'VurucuTim Güncellemesi',
    backgroundColor: '#1e1e1e',
    autoHideMenuBar: true,
    frame: false,                 // chromeless for cleaner look
    alwaysOnTop: true,
    skipTaskbar: false,
    webPreferences: {
      preload: path.join(__dirname, '..', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  _dialogWin.loadFile(path.join(__dirname, '..', 'update-dialog', 'index.html'));
  _dialogWin.once('ready-to-show', () => {
    _dialogWin.show();
    _dialogWin.focus();
  });
  _dialogWin.on('closed', () => { _dialogWin = null; });
}

async function checkManually() {
  _manualTriggered = true;
  try {
    await autoUpdater.checkForUpdates();
  } catch (err) {
    log.error('updater manual check failed:', err);
  } finally {
    setTimeout(() => { _manualTriggered = false; }, 5000);
  }
}

function startBackgroundPolling() {
  const p = prefs.load();
  if (!p.autoUpdate) {
    log.info('updater: autoUpdate disabled in prefs — skipping polling');
    return;
  }
  // First check 30s after app boot (let panel load)
  setTimeout(() => autoUpdater.checkForUpdates().catch((e) => log.warn('updater initial check failed:', e.message)), 30 * 1000);
  // Then every 6 hours
  setInterval(() => {
    if (prefs.load().autoUpdate) {
      autoUpdater.checkForUpdates().catch((e) => log.warn('updater interval check failed:', e.message));
    }
  }, 6 * 60 * 60 * 1000);
}

function state() { return _updateState; }

module.exports = { init, checkManually, startBackgroundPolling, state, openDialog };
