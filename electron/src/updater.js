const { autoUpdater } = require('electron-updater');
const { dialog, app } = require('electron');
const log = require('./logger');
const prefs = require('./preferences');

autoUpdater.logger = log;
autoUpdater.autoDownload = true;
autoUpdater.autoInstallOnAppQuit = false;   // user must explicitly accept

let _ctx = null;
let _manualTriggered = false;
let _updateState = 'idle';   // idle | checking | available | downloading | downloaded | error

function init(ctx) {
  _ctx = ctx;

  autoUpdater.on('checking-for-update', () => {
    _updateState = 'checking';
    log.info('updater: checking');
  });
  autoUpdater.on('update-not-available', (info) => {
    _updateState = 'idle';
    log.info('updater: up to date', info?.version);
    if (_manualTriggered) {
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
    promptInstall(info.version);
  });
  autoUpdater.on('error', (err) => {
    _updateState = 'error';
    log.error('updater: error', err);
    if (_manualTriggered) {
      try { dialog.showErrorBox('Güncelleme hatası', err.message || String(err)); } catch (_) {}
    }
  });
}

async function promptInstall(version) {
  let r;
  try {
    r = await dialog.showMessageBox({
      type: 'info',
      title: 'VurucuTim Güncellemesi Hazır',
      message: `v${version} yüklenmeye hazır.`,
      detail: 'Yüklemek için uygulama yeniden başlatılacak. Aktif işler iptal olabilir.',
      buttons: ['Yükle ve Yeniden Başlat', 'Sonra'],
      defaultId: 0,
      cancelId: 1,
    });
  } catch (_) {
    return;
  }
  if (r.response === 0) {
    if (_ctx?.beforeQuit) {
      try { await _ctx.beforeQuit(); } catch (e) { log.warn('updater beforeQuit failed:', e.message); }
    }
    autoUpdater.quitAndInstall(false, true);
  }
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

module.exports = { init, checkManually, startBackgroundPolling, state };
