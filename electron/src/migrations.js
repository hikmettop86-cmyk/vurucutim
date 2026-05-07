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

async function maybeMigrate(onProgress) {
  const current = app.getVersion();
  const last = readLastVersion();
  if (last === current) return { migrated: false };
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

  writeLastVersion(current);
  return { migrated: true, from: last, to: current };
}

module.exports = { maybeMigrate, readLastVersion, writeLastVersion };
