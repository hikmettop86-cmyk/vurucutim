const { app, BrowserWindow, dialog } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const paths = require('./src/paths');
const runner = require('./src/python-runner');

// Force Local AppData (not Roaming) and capitalized app name
// Reason: Roaming AppData may sync via OneDrive/AD policies, causing SQLite lock corruption.
// Must run before app.whenReady() — userData path is locked once any path API is called.
app.setName('VurucuTim');
const _localAppData = process.env.LOCALAPPDATA || path.join(require('node:os').homedir(), 'AppData', 'Local');
app.setPath('userData', path.join(_localAppData, 'VurucuTim'));

let mainWindow = null;

function ensureUserDirs() {
  for (const d of [
    paths.userData(),
    paths.configDir(),
    paths.dataDir(),
    paths.logsDir(),
    paths.outputDir(),
    paths.musicRoot(),
    paths.depsDir(),
  ]) {
    fs.mkdirSync(d, { recursive: true });
  }
}

function createMainWindow(url) {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 960,
    minHeight: 600,
    title: 'VurucuTim',
    backgroundColor: '#1e1e1e',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(url);
  mainWindow.on('closed', () => { mainWindow = null; });
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
      `Bot arka planı başlatılamadı.\n\nHata: ${err.message}\n\nLog: ${stderrLog}`
    );
    app.quit();
  }
}

app.whenReady().then(async () => {
  ensureUserDirs();
  const log = require('./src/logger');
  log.info('app ready, version:', app.getVersion());
  await bootFlaskAndOpenPanel();
});

app.on('window-all-closed', () => {
  app.quit();
});

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
