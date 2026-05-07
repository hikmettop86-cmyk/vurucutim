const { Tray, Menu, app, shell, nativeImage } = require('electron');
const path = require('node:path');
const paths = require('./paths');
const prefs = require('./preferences');
const log = require('./logger');

let tray = null;
let _ctx = null;

function buildMenu() {
  const p = prefs.load();
  const running = _ctx?.runner?.isRunning() ? '● Çalışıyor' : '● Durdu';
  return Menu.buildFromTemplate([
    { label: 'Paneli Aç', click: () => _ctx.showMain?.() },
    { type: 'separator' },
    { label: `Bot Durumu: ${running}`, enabled: false },
    { type: 'separator' },
    { label: 'Sağlık Kontrolü…', click: () => _ctx.openWizard?.({ repair: true }) },
    { label: 'Güncellemeleri Kontrol Et…', click: () => _ctx.checkUpdates?.() },
    { type: 'separator' },
    { label: 'Logları Aç', click: () => shell.openPath(paths.logsDir()) },
    { label: 'Veri Klasörünü Aç', click: () => shell.openPath(paths.userData()) },
    { type: 'separator' },
    {
      label: 'Ayarlar',
      submenu: [
        {
          label: 'Sistem başlarken aç',
          type: 'checkbox',
          checked: p.autostart,
          click: (item) => _ctx.setAutostart?.(item.checked),
        },
        {
          label: 'Otomatik güncelleme',
          type: 'checkbox',
          checked: p.autoUpdate,
          click: (item) => prefs.update({ autoUpdate: item.checked }),
        },
      ],
    },
    { type: 'separator' },
    { label: `Hakkında (v${app.getVersion()})`, enabled: false },
    { type: 'separator' },
    { label: 'Çıkış', click: () => _ctx.quitApp?.() },
  ]);
}

function refreshMenu() {
  if (tray) tray.setContextMenu(buildMenu());
}

function init(ctx) {
  _ctx = ctx;
  const iconPath = path.join(__dirname, '..', 'assets', 'icon.png');
  const img = nativeImage.createFromPath(iconPath);
  tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img);
  tray.setToolTip('VurucuTim');
  tray.setContextMenu(buildMenu());
  tray.on('click', () => _ctx.showMain?.());
  log.info('tray initialized');
  return tray;
}

function destroy() {
  if (tray) { tray.destroy(); tray = null; }
}

function notifyHidden() {
  if (!tray) return;
  try {
    tray.displayBalloon({
      title: 'VurucuTim arka planda çalışıyor',
      content: 'Tamamen kapatmak için tray ikonuna sağ tıklayıp Çıkış de.',
      iconType: 'info',
    });
  } catch (err) {
    log.warn('tray.displayBalloon failed:', err.message);
  }
}

module.exports = { init, refreshMenu, destroy, notifyHidden };
