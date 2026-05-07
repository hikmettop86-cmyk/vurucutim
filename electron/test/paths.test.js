const { test } = require('node:test');
const assert = require('node:assert');
const path = require('node:path');

// paths.js needs `app` from electron — we mock it before require
const electronMock = {
  app: {
    getPath: (key) => {
      if (key === 'userData') return 'C:\\Users\\Test\\AppData\\Local\\VurucuTim';
      if (key === 'exe') return 'C:\\Program Files\\VurucuTim\\VurucuTim.exe';
      throw new Error(`unexpected key: ${key}`);
    },
    isPackaged: true
  }
};
require.cache[require.resolve('electron')] = { exports: electronMock };

const paths = require('../src/paths');

test('userData() returns app userData path', () => {
  assert.strictEqual(paths.userData(), 'C:\\Users\\Test\\AppData\\Local\\VurucuTim');
});

test('configDir is under userData', () => {
  assert.ok(paths.configDir().endsWith(path.join('VurucuTim', 'config')));
});

test('venvPython resolves to embedded python (no real venv on embed)', () => {
  // venvPython is now an alias for embeddedPython since embedded Python lacks venv module
  assert.strictEqual(paths.venvPython(), paths.embeddedPython());
});

test('sitePackagesDir is under userData/python-site-packages', () => {
  assert.ok(paths.sitePackagesDir().endsWith(path.join('VurucuTim', 'python-site-packages')));
});

test('embeddedPython is under resources/python in packaged app', () => {
  assert.ok(paths.embeddedPython().includes(path.join('resources', 'python', 'python.exe')));
});

test('ffmpegBin is under userData/deps/ffmpeg/bin', () => {
  assert.ok(paths.ffmpegBin().includes(path.join('deps', 'ffmpeg', 'bin', 'ffmpeg.exe')));
});

test('shortBotSrc is under resources/short-bot/src in packaged app', () => {
  assert.ok(paths.shortBotSrc().includes(path.join('resources', 'short-bot', 'src')));
});

test('initializedFlag is under userData', () => {
  assert.ok(paths.initializedFlag().endsWith(path.join('VurucuTim', '.initialized')));
});
