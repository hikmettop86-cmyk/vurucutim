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

function venvDir() {
  return path.join(userData(), 'venv');
}

function venvPython() {
  return path.join(venvDir(), 'Scripts', 'python.exe');
}

function venvPip() {
  return path.join(venvDir(), 'Scripts', 'pip.exe');
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
  venvDir, venvPython, venvPip,
  depsDir, ffmpegBin,
  preferencesFile, initializedFlag,
  resourcesDir, embeddedPython,
  shortBotRoot, shortBotSrc, settingsExample, bundledMusic,
};
