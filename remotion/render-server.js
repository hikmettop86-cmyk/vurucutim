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
      const composition = await renderer.selectComposition({
        serveUrl,
        id: compositionId,
        inputProps: props || {},
      });
      // calculateMetadata in Root.tsx reads durationSeconds from props;
      // override with explicit durationInFrames if supplied (preview is
      // typically short so we don't care, but support both paths).
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
