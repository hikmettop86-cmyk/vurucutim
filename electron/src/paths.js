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

function templatesDir() {
  // Writable templates dir under userData. Original (read-only) templates live under
  // shortBotRoot/templates and are copied here at first boot. CSS files for new channels
  // are generated into templates/css/ at runtime.
  return path.join(userData(), 'templates');
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

function bundledTemplates() {
  return path.join(shortBotRoot(), 'templates');
}

// --- Bundled Node + Remotion (Phase 3) -------------------------------------

function nodeHome() {
  // packaged: <resources>/node/   |  dev: rely on system node on PATH
  return app.isPackaged
    ? path.join(resourcesDir(), 'node')
    : '';   // empty → Python falls back to PATH lookup
}

function bundledRemotionSrc() {
  // Read-only template source bundled with the installer.
  // packaged: <resources>/short-bot/remotion/  | dev: <repo>/remotion/
  return app.isPackaged
    ? path.join(shortBotRoot(), 'remotion')
    : path.resolve(__dirname, '..', '..', 'remotion');
}

function remotionUserDir() {
  // Writable copy under userData. Bundled remotion/{src,package.json,...}
  // is copied here on first boot so `npm install` can write node_modules
  // (resources/ is read-only on Windows installer).
  return path.join(userData(), 'remotion');
}

module.exports = {
  APP_NAME,
  userData, configDir, settingsYaml,
  dataDir, logsDir, outputDir, musicRoot, templatesDir,
  sitePackagesDir, venvDir, venvPython, venvPip,
  depsDir, ffmpegBin,
  preferencesFile, initializedFlag,
  resourcesDir, embeddedPython,
  shortBotRoot, shortBotSrc, settingsExample, bundledMusic, bundledTemplates,
  nodeHome, bundledRemotionSrc, remotionUserDir,
};
