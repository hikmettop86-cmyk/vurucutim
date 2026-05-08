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

test('detectClaudeCli returns ok with absolute path from `where claude`', async () => {
  mockExecResults = {
    'where claude': { err: null, stdout: 'C:\\Users\\X\\AppData\\Roaming\\npm\\claude.cmd\r\n' },
  };
  mockFs = {};
  const r = await detector.detectClaudeCli();
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.path, 'C:\\Users\\X\\AppData\\Roaming\\npm\\claude.cmd');
});

test('detectClaudeCli falls back to known npm path when `where` fails', async () => {
  mockExecResults = { 'where claude': { err: new Error('not found') } };
  // Simulate %APPDATA%\npm\claude.cmd existing on disk
  const candidates = detector._claudeCandidatePaths();
  mockFs = {};
  for (const c of candidates) mockFs[c] = false;
  const npmCmd = candidates.find((c) => c.endsWith('npm\\claude.cmd'));
  if (npmCmd) mockFs[npmCmd] = true;
  const r = await detector.detectClaudeCli();
  assert.strictEqual(r.status, 'ok');
  assert.strictEqual(r.path, npmCmd);
});

test('detectClaudeCli returns missing with action when nothing resolves', async () => {
  mockExecResults = { 'where claude': { err: new Error('not found') } };
  mockFs = {};
  for (const c of detector._claudeCandidatePaths()) mockFs[c] = false;
  const r = await detector.detectClaudeCli();
  assert.strictEqual(r.status, 'missing');
  assert.ok(r.action);
  assert.strictEqual(r.action.type, 'open-url');
  assert.ok(r.action.url.startsWith('https://'));
});

test('detectAll returns array with status for each dep', async () => {
  mockExecResults = {
    'ffmpeg -version': { err: null, stdout: 'ffmpeg' },
    'where claude': { err: null, stdout: 'C:\\Users\\X\\AppData\\Roaming\\npm\\claude.cmd\r\n' },
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
