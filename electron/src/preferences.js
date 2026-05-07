const fs = require('node:fs');
const paths = require('./paths');

const DEFAULTS = {
  autostart: false,
  autoUpdate: true,
};

function load() {
  try {
    const raw = fs.readFileSync(paths.preferencesFile(), 'utf-8');
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch (_) {
    return { ...DEFAULTS };
  }
}

function save(prefs) {
  const merged = { ...DEFAULTS, ...prefs };
  fs.writeFileSync(paths.preferencesFile(), JSON.stringify(merged, null, 2), 'utf-8');
  return merged;
}

function update(partial) {
  return save({ ...load(), ...partial });
}

module.exports = { load, save, update, DEFAULTS };
