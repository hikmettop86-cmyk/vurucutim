const fs = require('node:fs');
const paths = require('./paths');

const DEFAULTS = {
  autostart: false,
  autoUpdate: true,
};

function load() {
  let raw;
  try {
    raw = fs.readFileSync(paths.preferencesFile(), 'utf-8');
  } catch (err) {
    if (err.code !== 'ENOENT') {
      // ENOENT (file missing) is the normal first-run case — don't log.
      // Other errors (permissions, I/O) are unexpected — log them.
      const log = require('./logger');
      log.warn('preferences read failed, using defaults:', err.message);
    }
    return { ...DEFAULTS };
  }
  try {
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch (err) {
    const log = require('./logger');
    const backup = paths.preferencesFile() + '.corrupt-' + Date.now();
    try { fs.renameSync(paths.preferencesFile(), backup); } catch (_) {}
    log.warn(`preferences.json corrupt, backed up to ${backup}, using defaults:`, err.message);
    return { ...DEFAULTS };
  }
}

function save(prefs) {
  // Whitelist keys + type-check against DEFAULTS to prevent typo'd or hostile entries.
  const validated = {};
  for (const [k, defaultVal] of Object.entries(DEFAULTS)) {
    if (k in prefs && typeof prefs[k] === typeof defaultVal) {
      validated[k] = prefs[k];
    }
  }
  const merged = { ...DEFAULTS, ...validated };
  fs.writeFileSync(paths.preferencesFile(), JSON.stringify(merged, null, 2), 'utf-8');
  return merged;
}

function update(partial) {
  return save({ ...load(), ...partial });
}

module.exports = { load, save, update, DEFAULTS };
