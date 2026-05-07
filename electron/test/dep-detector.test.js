const { test } = require('node:test');
const assert = require('node:assert');

// Mock electron + child_process before requiring the module under test
const electronMock = {
  app: {
    getPath: (k) => k === 'exe'
      ? 'C:\\Program Files\\VurucuTim\\VurucuTim.exe'
      : 'C:\\Users\\Test\\AppData\\Local\\VurucuTim',
    isPackaged: true,
  }
};
require.cache[require.resolve('electron')] = { exports: electronMock };

let mockExecResults = {};
require.cache[require.resolve('child_process')] = {
  exports: {
    execFile: (cmd, args, opts, cb) => {
      const key = `${cmd} ${(args || []).join(' ')}`.trim();
      const r = mockExecResults[key];
      if (!r) return cb(new Error(`unmocked exec: ${key}`));
      cb(r.err, r.stdout || '', r.stderr || '');
    }
  }
};
const fs = require('node:fs');
const origExists = fs.existsSync;
let mockFs = {};
fs.existsSync = (p) => p in mockFs ? mockFs[p] : origExists(p);

const detector = require('../src/dep-detector');

test('detectFfmpeg returns ok when system ffmpeg available', async () => {
  mockExecResults = { 'ffmpeg -version': { err: null, stdout: 'ffmpeg version 6.0' } };
  mockFs = {};
  const r = await detector.detectFfmpeg();
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.source, 'system');
});

test('detectFfmpeg returns ok when bundled ffmpeg available', async () => {
  mockExecResults = { 'ffmpeg -version': { err: new Error('not found') } };
  mockFs = { 'C:\\Users\\Test\\AppData\\Local\\VurucuTim\\deps\\ffmpeg\\bin\\ffmpeg.exe': true };
  const r = await detector.detectFfmpeg();
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.source, 'bundled');
});

test('detectFfmpeg returns missing when neither available', async () => {
  mockExecResults = { 'ffmpeg -version': { err: new Error('not found') } };
  mockFs = {};
  const r = await detector.detectFfmpeg();
  assert.strictEqual(r.status, 'missing');
});

test('detectClaudeCli returns ok when claude --version succeeds', async () => {
  mockExecResults = { 'claude --version': { err: null, stdout: '0.5.0' } };
  const r = await detector.detectClaudeCli();
  assert.strictEqual(r.status, 'ok');
});

test('detectClaudeCli returns missing with action when not on PATH', async () => {
  mockExecResults = { 'claude --version': { err: new Error('not found') } };
  const r = await detector.detectClaudeCli();
  assert.strictEqual(r.status, 'missing');
  assert.ok(r.action);
  assert.strictEqual(r.action.type, 'open-url');
  assert.ok(r.action.url.startsWith('https://'));
});

test('detectAll returns array with status for each dep', async () => {
  mockExecResults = {
    'ffmpeg -version': { err: null, stdout: 'ffmpeg' },
    'claude --version': { err: null, stdout: '0.5.0' },
    'claude --print ping': { err: null, stdout: 'pong' },
  };
  mockFs = {
    'C:\\Users\\Test\\AppData\\Local\\VurucuTim\\venv\\Scripts\\python.exe': false,
  };
  const list = await detector.detectAll();
  assert.ok(Array.isArray(list));
  assert.ok(list.length >= 4);
  for (const item of list) {
    assert.ok('id' in item, `missing id: ${JSON.stringify(item)}`);
    assert.ok('label' in item, `missing label: ${JSON.stringify(item)}`);
    assert.ok('status' in item, `missing status: ${JSON.stringify(item)}`);
  }
});
