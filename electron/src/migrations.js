const fs = require('node:fs');
const path = require('node:path');
const { app } = require('electron');
const installer = require('./dep-installer');
const paths = require('./paths');
const log = require('./logger');

function lastInstalledVersionFile() {
  return path.join(paths.userData(), '.last-version');
}

function readLastVersion() {
  try { return fs.readFileSync(lastInstalledVersionFile(), 'utf-8').trim(); }
  catch { return null; }
}

function writeLastVersion(v) {
  fs.writeFileSync(lastInstalledVersionFile(), v, 'utf-8');
}

function copyDirRecursive(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (entry.name === 'node_modules') continue;  // never copy the 500 MB tree
    const s = path.join(src, entry.name);
    const d = path.join(dest, entry.name);
    if (entry.isDirectory()) copyDirRecursive(s, d);
    else fs.copyFileSync(s, d);
  }
}

function syncRemotionUserDir() {
  // Bundled remotion is read-only inside the installer; user-side npm install
  // needs a writable copy. Copy src/, package.json, etc. (NOT node_modules)
  // to userData/remotion/ on every boot so app updates that touch the templates
  // propagate to existing installs.
  const bundled = paths.bundledRemotionSrc();
  const userDir = paths.remotionUserDir();
  if (!fs.existsSync(bundled)) {
    log.info('migration: bundled remotion not found at', bundled, '(skipping)');
    return;
  }
  // Strategy: rsync-style overwrite of src/, package.json, package-lock.json,
  // tsconfig.json, remotion.config.ts, render-server.js. Leave node_modules
  // in place so the lazy-installed deps survive app updates.
  for (const name of ['src', 'package.json', 'package-lock.json',
                       'tsconfig.json', 'remotion.config.ts',
                       'render-server.js']) {
    const s = path.join(bundled, name);
    const d = path.join(userDir, name);
    if (!fs.existsSync(s)) continue;
    if (fs.statSync(s).isDirectory()) {
      // Wipe destination subtree first so deleted files in upstream don't linger
      fs.rmSync(d, { recursive: true, force: true });
      copyDirRecursive(s, d);
    } else {
      fs.mkdirSync(path.dirname(d), { recursive: true });
      fs.copyFileSync(s, d);
    }
  }
  log.info('migration: remotion userdir synced at', userDir);

  // Tell the running render daemon (if any) to exit so the next preview
  // request respawns it with the freshly-synced render-server.js code.
  // Without this, the daemon keeps the old bundle + old logic in memory
  // and renders fail in surprising ways after app updates.
  try {
    const req = require('node:http').request({
      hostname: '127.0.0.1',
      port: 3219,
      path: '/shutdown',
      method: 'POST',
      timeout: 1000,
    });
    req.on('error', () => {});  // daemon not running → no-op
    req.end();
    log.info('migration: render daemon shutdown signaled');
  } catch (e) {
    /* swallow */
  }
}

async function maybeMigrate(onProgress) {
  const current = app.getVersion();
  const last = readLastVersion();
  if (last === current) {
    // Even on no-op version, ensure remotion userdir reflects current install
    // (catches the case where the user upgraded the app outside our normal flow)
    try { syncRemotionUserDir(); } catch (e) { log.warn('remotion sync skipped:', e.message); }
    return { migrated: false };
  }
  log.info(`migration: ${last ?? '(none)'} → ${current}`);

  // Re-run pip install -e (idempotent, fast if no changes)
  if (fs.existsSync(paths.venvPython())) {
    onProgress?.('Python paketleri kontrol ediliyor…');
    try {
      await installer.installPipPackages({ onProgress });
    } catch (e) {
      log.warn('migration: pip install failed (continuing):', e.message);
    }
    // Playwright: if upgraded, install will detect outdated Chromium
    onProgress?.('Playwright kontrol ediliyor…');
    try {
      await installer.installPlaywrightChromium({ onProgress });
    } catch (e) {
      log.warn('migration: playwright re-install failed (non-fatal):', e.message);
    }
  } else {
    log.info('migration: no venv yet — skipping (wizard will install)');
  }

  // Sync the remotion userdir so the channel.renderer='remotion' path works
  // immediately after an app update (node_modules install still lazy).
  onProgress?.('Remotion şablonları senkronize ediliyor…');
  try { syncRemotionUserDir(); }
  catch (e) { log.warn('migration: remotion sync failed (non-fatal):', e.message); }

  writeLastVersion(current);
  return { migrated: true, from: last, to: current };
}

module.exports = { maybeMigrate, readLastVersion, writeLastVersion };
