const path = require('node:path');
const { app } = require('electron');

const APP_NAME = 'VurucuTim';

function userData() {
  return app.getPath('userData');
}

function configDir() {
  return path.join(userData(), 'config');
}

function settingsYaml() {
  return path.join(configDir(), 'settings.yaml');
}

function dataDir() {
  return path.join(userData(), 'data');
}

function logsDir() {
  return path.join(userData(), 'logs');
}

function outputDir() {
  return path.join(userData(), 'output');
}

function musicRoot() {
  return path.join(userData(), 'assets', 'music');
}

function sitePackagesDir() {
  // Flat pip --target dir (replaces traditional venv — embedded Python lacks venv module)
  return path.join(userData(), 'python-site-packages');
}

// Backwards-compat aliases (still used by some modules; will be removed in future cleanup):
function venvDir() {
  return sitePackagesDir();
}

function venvPython() {
  // No real venv interpreter — always use embedded Python with PYTHONPATH set elsewhere
  return embeddedPython();
}

function venvPip() {
  // pip is invoked as `python -m pip` — this path may not exist physically
  return path.join(sitePackagesDir(), 'Scripts', 'pip.exe');
}

function depsDir() {
  return path.join(userData(), 'deps');
}

function ffmpegBin() {
  return path.join(depsDir(), 'ffmpeg', 'bin', 'ffmpeg.exe');
}

function preferencesFile() {
  return path.join(userData(), 'preferences.json');
}

function initializedFlag() {
  return path.join(userData(), '.initialized');
}

function resourcesDir() {
  // packaged: <install>/resources/  | dev: <repo>/electron/
  return app.isPackaged
    ? path.dirname(app.getPath('exe')).replace(/\\?$/, '') + path.sep + 'resources'
    : path.resolve(__dirname, '..', '..');
}

function embeddedPython() {
  return app.isPackaged
    ? path.join(resourcesDir(), 'python', 'python.exe')
    : 'python';   // dev mode: system python
}

function shortBotRoot() {
  return app.isPackaged
    ? path.join(resourcesDir(), 'short-bot')
    : path.resolve(__dirname, '..', '..');
}

function shortBotSrc() {
  return path.join(shortBotRoot(), 'src');
}

function settingsExample() {
  return path.join(shortBotRoot(), 'config', 'settings.yaml.example');
}

function bundledMusic() {
  return path.join(shortBotRoot(), 'assets', 'music');
}

module.exports = {
  APP_NAME,
  userData, configDir, settingsYaml,
  dataDir, logsDir, outputDir, musicRoot,
  sitePackagesDir, venvDir, venvPython, venvPip,
  depsDir, ffmpegBin,
  preferencesFile, initializedFlag,
  resourcesDir, embeddedPython,
  shortBotRoot, shortBotSrc, settingsExample, bundledMusic,
};
