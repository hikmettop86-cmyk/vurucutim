const depList = document.getElementById('dep-list');
const summary = document.getElementById('summary');
const totalMb = document.getElementById('total-mb');
const eta = document.getElementById('eta');
const progress = document.getElementById('progress');
const barFill = document.getElementById('bar-fill');
const phaseLabel = document.getElementById('phase-label');
const logEl = document.getElementById('log');
const errorEl = document.getElementById('error');
const errorMsg = document.getElementById('error-msg');
const btnInstall = document.getElementById('btn-install');
const btnSkip = document.getElementById('btn-skip');
const btnRetry = document.getElementById('btn-retry');
const btnSkipAfterError = document.getElementById('btn-skip-after-error');
const btnCopyError = document.getElementById('btn-copy-error');
const btnOpenLogs = document.getElementById('btn-open-logs');
const optAutostart = document.getElementById('opt-autostart');

let currentDeps = [];
let unsubProgress = null;

function renderDepRow(dep) {
  const row = document.createElement('div');
  row.className = `dep-row ${dep.status}`;
  row.dataset.id = dep.id;
  row.innerHTML = `
    <span class="icon"></span>
    <span class="label"></span>
    <span class="detail"></span>
  `;
  row.querySelector('.label').textContent = dep.label;
  row.querySelector('.detail').textContent = dep.detail || (dep.status === 'ok' ? '' : 'eksik');
  if (dep.action?.type === 'open-url') {
    const btn = document.createElement('button');
    btn.className = 'secondary';
    btn.textContent = 'Tarayıcıda Aç';
    btn.onclick = () => window.vt.openExternal(dep.action.url);
    row.appendChild(btn);
  }
  return row;
}

function setRowStatus(id, status, detail) {
  const row = depList.querySelector(`[data-id="${id}"]`);
  if (!row) return;
  row.className = `dep-row ${status}`;
  if (detail !== undefined) row.querySelector('.detail').textContent = detail;
}

function estimateTotalMb(deps) {
  let total = 0;
  for (const d of deps) {
    if (d.status === 'ok') continue;
    if (d.id === 'pip') total += 50;
    if (d.id === 'chromium') total += 150;
    if (d.id === 'ffmpeg') total += 80;
  }
  return total;
}

function appendLog(text) {
  logEl.textContent += text + '\n';
  logEl.scrollTop = logEl.scrollHeight;
}

async function refreshDeps() {
  depList.innerHTML = '';
  currentDeps = await window.vt.detectAll();
  for (const dep of currentDeps) depList.appendChild(renderDepRow(dep));

  const missing = currentDeps.filter((d) => d.status !== 'ok');
  const installable = missing.filter((d) => !d.action || d.action.type !== 'open-url');

  if (missing.length === 0) {
    btnInstall.disabled = true;
    btnInstall.textContent = 'Her Şey Hazır';
    summary.classList.add('hidden');
    return;
  }

  const mb = estimateTotalMb(currentDeps);
  if (mb > 0) {
    summary.classList.remove('hidden');
    totalMb.textContent = `~${mb} MB`;
    eta.textContent = mb > 200 ? '8-12 dk' : mb > 80 ? '4-7 dk' : '2-4 dk';
  }
  btnInstall.disabled = installable.length === 0;
}

async function loadPrefs() {
  const p = await window.vt.getPreferences();
  optAutostart.checked = !!p.autostart;
}

async function startInstall() {
  errorEl.classList.add('hidden');
  progress.classList.remove('hidden');
  btnInstall.disabled = true;
  btnSkip.disabled = true;

  const phaseOrder = ['venv', 'pip', 'chromium', 'ffmpeg', 'config', 'music', 'db'];
  const phaseLabels = {
    venv: 'Sanal ortam', pip: 'Python paketleri', chromium: 'Playwright Chromium',
    ffmpeg: 'ffmpeg', config: 'Ayarlar', music: 'Müzik kütüphanesi', db: 'Veritabanı',
  };

  // Cleanup any prior listener (idempotent — Retry path may call us twice)
  if (unsubProgress) { unsubProgress(); unsubProgress = null; }
  unsubProgress = window.vt.onProgress(({ phase, text }) => {
    if (phase) {
      phaseLabel.textContent = `${phaseLabels[phase] || phase}: ${text}`;
      const idx = phaseOrder.indexOf(phase);
      if (idx >= 0) {
        const pct = Math.floor(((idx + 1) / phaseOrder.length) * 100);
        barFill.style.width = `${pct}%`;
      }
      const depMap = { venv: 'venv', pip: 'pip', chromium: 'chromium', ffmpeg: 'ffmpeg' };
      if (depMap[phase]) setRowStatus(depMap[phase], 'installing', text);
    }
    appendLog(text);
  });

  try {
    await window.vt.installMissing();
    barFill.style.width = '100%';
    phaseLabel.textContent = 'Tamamlandı.';
    await refreshDeps();
    await window.vt.setPreferences({ autostart: optAutostart.checked });
    await window.vt.finishWizard({ status: 'ok' });
  } catch (e) {
    errorEl.classList.remove('hidden');
    // Tüm log buffer'ından son ~50 satırı ekle — IPC error.message her zaman
    // tail içermeyebilir (örn. JSON serialization), o yüzden renderer-side
    // log'u da iliştir.
    const logTail = (logEl.textContent || '').split('\n').filter(Boolean).slice(-50).join('\n');
    const fullErr = (e.message || String(e))
      + (logTail ? `\n\n──────── Son log satırları ────────\n${logTail}` : '');
    errorMsg.textContent = fullErr;
    errorMsg.scrollTop = errorMsg.scrollHeight;
    btnInstall.disabled = false;
    btnSkip.disabled = false;
  } finally {
    if (unsubProgress) { unsubProgress(); unsubProgress = null; }
  }
}

btnInstall.addEventListener('click', startInstall);
btnSkip.addEventListener('click', async () => {
  await window.vt.setPreferences({ autostart: optAutostart.checked });
  await window.vt.finishWizard({ status: 'skipped' });
});
btnRetry.addEventListener('click', startInstall);
btnSkipAfterError.addEventListener('click', async () => {
  await window.vt.setPreferences({ autostart: optAutostart.checked });
  await window.vt.finishWizard({ status: 'partial' });
});

btnCopyError.addEventListener('click', async () => {
  const text = errorMsg.textContent || '';
  const meta = `VurucuTim Kurulum Hatası\nVersiyon: ${window.vt?.version || '?'}\nTarih: ${new Date().toISOString()}\n\n`;
  const ok = await window.vt.copyToClipboard(meta + text);
  btnCopyError.classList.add('copied');
  btnCopyError.textContent = ok ? '✓ Kopyalandı' : '✗ Kopyalanamadı';
  setTimeout(() => {
    btnCopyError.classList.remove('copied');
    btnCopyError.textContent = '📋 Hatayı Kopyala';
  }, 2200);
});

btnOpenLogs.addEventListener('click', async () => {
  const res = await window.vt.openLogsFolder();
  if (!res?.ok) {
    btnOpenLogs.textContent = `✗ Açılamadı: ${res?.path || ''}`;
    setTimeout(() => { btnOpenLogs.textContent = '📂 Log Klasörünü Aç'; }, 3000);
  }
});

(async () => {
  try {
    await loadPrefs();
    await refreshDeps();
  } catch (e) {
    console.error(e);
    errorEl.classList.remove('hidden');
    errorMsg.textContent = `Kontrol hatası: ${e.message}`;
  }
})();
