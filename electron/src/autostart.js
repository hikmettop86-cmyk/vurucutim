const { app } = require('electron');

function set(enabled) {
  app.setLoginItemSettings({
    openAtLogin: enabled,
    openAsHidden: true,
    path: process.execPath,
    args: ['--hidden'],
  });
}

function get() {
  const s = app.getLoginItemSettings({ args: ['--hidden'] });
  return s.openAtLogin;
}

function syncFromPrefs(prefs) {
  const desired = prefs.load().autostart;
  const actual = get();
  if (desired !== actual) set(desired);
}

module.exports = { set, get, syncFromPrefs };
