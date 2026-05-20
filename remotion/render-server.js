#!/usr/bin/env node
/**
 * Remotion render daemon — bundles ONCE and reuses for many renders.
 *
 * Why: spawning `npx remotion still` per preview takes ~10-15s for the
 * bundle phase alone. Under load (e.g. 6 shuffle thumbnails) the CPU/disk
 * contention makes them all time out. This daemon keeps the bundle warm
 * in memory and renders new stills in ~1-2s each.
 *
 * Protocol (HTTP on 127.0.0.1:3219):
 *   GET  /health                       → 200 ok
 *   POST /render-still {compositionId, props, frame, outputPath, durationInFrames?}
 *                                      → 200 {success:true}  | 500 {error: "..."}
 *
 * Lifecycle: Python's render_still() probes /health; if down, spawns this
 * script as a background process and retries. The server exits cleanly on
 * SIGTERM but otherwise runs indefinitely.
 */
const http = require('node:http');
const path = require('node:path');

const PORT = 3219;
const ENTRY_POINT = path.resolve(__dirname, 'src/index.ts');

let bundlePromise = null;
let log = (msg) => console.log(`[render-server] ${msg}`);

async function pickFreePort() {
  // Try ports in 3221-3299 — first free wins. Each render needs its own
  // port for Remotion's internal HTTP server; reusing across rapid calls
  // hits EADDRINUSE because the previous socket lingers briefly.
  const net = require('node:net');
  for (let p = 3221; p < 3300; p++) {
    const free = await new Promise((resolve) => {
      const s = net.createServer();
      s.unref();
      s.on('error', () => resolve(false));
      s.listen(p, '127.0.0.1', () => {
        s.close(() => resolve(true));
      });
    });
    if (free) return p;
  }
  // Last resort — let Remotion pick. Risk: it picks 3000 → Next.js collision.
  return null;
}

async function getServeUrl() {
  if (!bundlePromise) {
    log(`bundling ${ENTRY_POINT} (one-time)…`);
    const t0 = Date.now();
    bundlePromise = require('@remotion/bundler').bundle({
      entryPoint: ENTRY_POINT,
      onProgress: (pct) => {
        if (pct % 25 === 0) log(`bundle ${pct}%`);
      },
    }).then((url) => {
      log(`bundle ready in ${Math.round((Date.now() - t0) / 100) / 10}s → ${url}`);
      return url;
    }).catch((e) => {
      log(`bundle FAILED: ${e.message}`);
      bundlePromise = null;  // allow retry
      throw e;
    });
  }
  return bundlePromise;
}

const server = http.createServer((req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, {'Content-Type': 'text/plain'});
    res.end('ok');
    return;
  }
  if (req.method === 'POST' && req.url === '/shutdown') {
    // Called by migrations.js after render-server.js itself is updated;
    // we exit cleanly so the next preview-request can respawn fresh code.
    log('shutdown requested — exiting in 200ms');
    res.writeHead(200, {'Content-Type': 'text/plain'});
    res.end('bye');
    setTimeout(() => process.exit(0), 200);
    return;
  }
  if (req.method !== 'POST' || req.url !== '/render-still') {
    res.writeHead(404);
    res.end();
    return;
  }
  let body = '';
  req.on('data', (chunk) => (body += chunk));
  req.on('end', async () => {
    const t0 = Date.now();
    let job;
    try {
      job = JSON.parse(body);
    } catch (e) {
      res.writeHead(400, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({error: `bad json: ${e.message}`}));
      return;
    }
    try {
      const {compositionId, props, frame, outputPath, durationInFrames} = job;
      if (!compositionId || !outputPath) {
        throw new Error('compositionId and outputPath are required');
      }
      const serveUrl = await getServeUrl();
      const renderer = require('@remotion/renderer');
      // CRITICAL: pass explicit `port` so Remotion doesn't pick 3000 default.
      // 3000 is hijacked by many users' Next.js / dev servers (we saw the
      // same bug back in Phase 0 — Remotion loads the wrong page and fails
      // with "Tried to go to localhost:3000 ... not a Remotion project").
      // Rotate within 3221-3299 — using a single hardcoded port collides on
      // consecutive renders (the previous server hasn't released its socket
      // before the next call tries to bind).
      const remotionPort = await pickFreePort();
      const composition = await renderer.selectComposition({
        serveUrl,
        id: compositionId,
        inputProps: props || {},
        port: remotionPort,
      });
      const finalComposition = durationInFrames
        ? {...composition, durationInFrames}
        : composition;
      await renderer.renderStill({
        composition: finalComposition,
        serveUrl,
        output: outputPath,
        inputProps: props || {},
        imageFormat: 'jpeg',
        jpegQuality: 80,
        frame: frame ?? 0,
        port: remotionPort,
      });
      const dt = Date.now() - t0;
      log(`rendered ${compositionId} frame=${frame} → ${path.basename(outputPath)} (${dt}ms)`);
      res.writeHead(200, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({success: true, ms: dt}));
    } catch (e) {
      log(`render FAILED: ${e.message}`);
      res.writeHead(500, {'Content-Type': 'application/json'});
      res.end(JSON.stringify({error: String(e?.message || e)}));
    }
  });
});

server.on('error', (err) => {
  if (err.code === 'EADDRINUSE') {
    // Another instance is already bound — that's fine, just exit silently.
    // Without this handler Node throws an uncaught error and the process
    // crashes loud, which under multi-spawn race leaves zombie node.exe's.
    log(`port ${PORT} already in use — another daemon is running; exiting cleanly`);
    process.exit(0);
  }
  log(`server error: ${err.message}`);
  process.exit(1);
});

server.listen(PORT, '127.0.0.1', () => {
  log(`listening on http://127.0.0.1:${PORT}`);
  // Pre-warm the bundle so the first real render is fast.
  getServeUrl().catch(() => {});
});

process.on('SIGTERM', () => {
  log('SIGTERM — shutting down');
  server.close(() => process.exit(0));
});
process.on('SIGINT', () => {
  log('SIGINT — shutting down');
  server.close(() => process.exit(0));
});
