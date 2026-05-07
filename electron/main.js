const { app, BrowserWindow } = require('electron');
const path = require('node:path');
const fs = require('node:fs');
const paths = require('./src/paths');

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

function createMainWindow() {
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

  // For now: load a placeholder page. Faz 2'de Python spawn + Flask URL gelecek.
  mainWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
    '<h1 style="font-family:sans-serif;color:#ccc;background:#1e1e1e;height:100vh;display:flex;align-items:center;justify-content:center;margin:0">VurucuTim — boot</h1>'
  ));

  mainWindow.on('closed', () => { mainWindow = null; });
}

app.whenReady().then(() => {
  ensureUserDirs();
  const log = require('./src/logger');
  log.info('app ready, version:', app.getVersion());
  createMainWindow();
});

app.on('window-all-closed', () => {
  app.quit();   // Faz 5'te tray ile değişecek
});
