const { app, BrowserWindow, dialog, ipcMain, shell } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const paths = require('./src/paths');
const runner = require('./src/python-runner');
const detector = require('./src/dep-detector');
const installer = require('./src/dep-installer');
const prefs = require('./src/preferences');
const tray = require('./src/tray');

// Force Local AppData (not Roaming) and capitalized app name
// Reason: Roaming AppData may sync via OneDrive/AD policies, causing SQLite lock corruption.
// Must run before app.whenReady() — userData path is locked once any path API is called.
app.setName('VurucuTim');
const _localAppData = process.env.LOCALAPPDATA || path.join(require('node:os').homedir(), 'AppData', 'Local');
app.setPath('userData', path.join(_localAppData, 'VurucuTim'));

let mainWindow = null;
let wizardWindow = null;
let _wizardResolve = null;

function ensureUserDirs() {
  for (const d of [
    paths.userData(), paths.configDir(), paths.dataDir(),
    paths.logsDir(), paths.outputDir(), paths.musicRoot(), paths.depsDir(),
  ]) fs.mkdirSync(d, { recursive: true });
}

function createMainWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280, height: 800, minWidth: 960, minHeight: 600,
    title: 'VurucuTim', backgroundColor: '#1e1e1e', autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true, nodeIntegration: false,
    },
  });
  mainWindow.loadURL(url);
  mainWindow.on('closed', () => { mainWindow = null; });
}

function createWizardWindow() {
  return new Promise((resolve) => {
    wizardWindow = new BrowserWindow({
      width: 720, height: 640, resizable: false, minimizable: false, maximizable: false,
      title: 'VurucuTim — Kurulum', backgroundColor: '#1e1e1e', autoHideMenuBar: true,
      webPreferences: {
        preload: path.join(__dirname, 'preload.js'),
        contextIsolation: true, nodeIntegration: false,
      },
    });
    wizardWindow.loadFile(path.join(__dirname, 'wizard', 'index.html'));
    wizardWindow.once('closed', () => {
      wizardWindow = null;
      // If finishWizard wasn't called (user closed via X), still resolve
      if (_wizardResolve) {
        const r = _wizardResolve;
        _wizardResolve = null;
        r({ status: 'closed' });
      }
    });
    _wizardResolve = resolve;
  });
}

function isFirstRun() {
  return !fs.existsSync(paths.initializedFlag());
}

function markInitialized() {
  fs.writeFileSync(paths.initializedFlag(), new Date().toISOString(), 'utf-8');
}

function registerIpc() {
  ipcMain.handle('vt:detect-all', () => detector.detectAll());
  ipcMain.handle('vt:install-missing', async (event) => {
    const deps = await detector.detectAll();
    await installer.installAll(deps, (payload) => {
      try { event.sender.send('vt:install-progress', payload); } catch (_) {}
    });
    return { ok: true };
  });
  ipcMain.handle('vt:open-external', (_e, url) => shell.openExternal(url));
  ipcMain.handle('vt:get-preferences', () => prefs.load());
  ipcMain.handle('vt:set-preferences', (_e, partial) => prefs.update(partial));
  ipcMain.handle('vt:finish-wizard', (_e, opts) => {
    markInitialized();
    if (_wizardResolve) {
      const r = _wizardResolve;
      _wizardResolve = null;
      r(opts || { status: 'ok' });
    }
    if (wizardWindow) wizardWindow.close();
  });
}

async function bootFlaskAndOpenPanel() {
  const log = require('./src/logger');
  try {
    const port = await runner.start();
    createMainWindow(`http://127.0.0.1:${port}`);
  } catch (err) {
    log.error('flask boot failed:', err);
    const stderrLog = path.join(paths.logsDir(), 'panel_stderr.log');
    dialog.showErrorBox(
      'VurucuTim açılamadı',
      `Bot arka planı başlatılamadı.\n\nHata: ${err.message}\n\nLog: ${stderrLog}\n\nSorunu çözmek için Sağlık Kontrolü çalıştırılabilir.`,
    );
    app.quit();
  }
}

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.focus();
    }
  });

  app.whenReady().then(async () => {
    ensureUserDirs();
    const log = require('./src/logger');
    log.info(`app ready, version: ${app.getVersion()}, firstRun: ${isFirstRun()}`);
    registerIpc();

    if (isFirstRun()) {
      const res = await createWizardWindow();
      log.info('wizard finished:', res.status);
      // Continue regardless of skip/ok — user may have only configured Claude manually
    }

    // Minimum bootstrap: settings.yaml MUST exist for Flask to boot.
    // copyExampleSettings is idempotent (skips if file exists).
    try {
      await installer.copyExampleSettings({ onProgress: (l) => log.info('bootstrap:', l) });
    } catch (err) {
      log.warn('bootstrap copyExampleSettings failed (non-fatal, may already exist):', err.message);
    }

    await bootFlaskAndOpenPanel();

    tray.init({
      runner,
      showMain: () => {
        if (!mainWindow) {
          const port = runner.port();
          if (port) createMainWindow(`http://127.0.0.1:${port}`);
          return;
        }
        if (mainWindow.isMinimized()) mainWindow.restore();
        mainWindow.show();
        mainWindow.focus();
      },
      openWizard: async () => {
        await createWizardWindow();
        tray.refreshMenu();
      },
      checkUpdates: () => {
        // Faz 6 will wire updater
        log.info('check-updates: not yet wired (Faz 6)');
      },
      setAutostart: (enabled) => {
        // Faz 5 Task 15 will wire autostart properly
        const p = require('./src/preferences');
        p.update({ autostart: enabled });
        tray.refreshMenu();
      },
      quitApp: async () => {
        app.isQuitting = true;
        try { await runner.stop(); } catch (_) {}
        tray.destroy();
        app.exit(0);
      },
    });
  });
}

app.on('window-all-closed', () => app.quit());

app.on('before-quit', async (e) => {
  if (runner.isRunning()) {
    e.preventDefault();
    const log = require('./src/logger');
    try {
      await runner.stop();
    } catch (err) {
      log.error('before-quit: runner.stop() failed:', err);
    }
    app.quit();
  }
});
