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

function killRemotionDaemonIfRunning() {
  // v0.1.94: Remotion was removed but users upgrading from older versions
  // may have a stale daemon listening on 3219. POST /shutdown one last time
  // so it exits cleanly; failures swallowed (daemon not running = no-op).
  try {
    const req = require('node:http').request({
      hostname: '127.0.0.1', port: 3219,
      path: '/shutdown', method: 'POST', timeout: 1000,
    });
    req.on('error', () => {});
    req.end();
  } catch (e) { /* swallow */ }
}

async function maybeMigrate(onProgress) {
  const current = app.getVersion();
  const last = readLastVersion();
  if (last === current) {
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

  // v0.1.94: kill any leftover Remotion daemon from older installs.
  killRemotionDaemonIfRunning();

  writeLastVersion(current);
  return { migrated: true, from: last, to: current };
}

module.exports = { maybeMigrate, readLastVersion, writeLastVersion };
