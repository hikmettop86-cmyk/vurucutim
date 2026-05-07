const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const tmp = path.join(os.tmpdir(), `vt-prefs-${Date.now()}`);
fs.mkdirSync(tmp, { recursive: true });

require.cache[require.resolve('electron')] = {
  exports: { app: {
    getPath: () => tmp,
    isPackaged: false,
    isReady: () => true,
  } }
};

const prefs = require('../src/preferences');

test('default preferences when file missing', () => {
  // Ensure clean state
  const f = path.join(tmp, 'preferences.json');
  if (fs.existsSync(f)) fs.unlinkSync(f);
  const p = prefs.load();
  assert.strictEqual(p.autostart, false);
  assert.strictEqual(p.autoUpdate, true);
});

test('save and reload roundtrip', () => {
  prefs.save({ autostart: true, autoUpdate: false });
  const p = prefs.load();
  assert.strictEqual(p.autostart, true);
  assert.strictEqual(p.autoUpdate, false);
});

test('partial update preserves other fields', () => {
  prefs.save({ autostart: true, autoUpdate: false });
  prefs.update({ autoUpdate: true });
  const p = prefs.load();
  assert.strictEqual(p.autostart, true);
  assert.strictEqual(p.autoUpdate, true);
});
