const { test } = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

// Mock electron + paths to avoid pulling them
require.cache[require.resolve('electron')] = {
  exports: { app: {
    getPath: () => os.tmpdir(),
    isPackaged: false,
    isReady: () => true,
  } }
};

const { downloadFile } = require('../src/dep-installer');

test('downloadFile saves http response to disk', async () => {
  const server = http.createServer((req, res) => {
    res.writeHead(200, { 'content-length': '5' });
    res.end('hello');
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const port = server.address().port;
  const dest = path.join(os.tmpdir(), `vt-test-${Date.now()}.bin`);
  // downloadFile uses https; for test, monkey-patch to http
  const https = require('node:https');
  const origGet = https.get;
  https.get = (url, opts, cb) => http.get(url, opts, cb);
  try {
    await downloadFile(`http://127.0.0.1:${port}/x`, dest);
    const got = fs.readFileSync(dest, 'utf-8');
    assert.strictEqual(got, 'hello');
  } finally {
    https.get = origGet;
    server.close();
    if (fs.existsSync(dest)) fs.unlinkSync(dest);
  }
});
