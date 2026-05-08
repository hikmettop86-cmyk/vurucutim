const machineIdEl = document.getElementById('machine-id');
const btnCopy = document.getElementById('btn-copy');
const serialInput = document.getElementById('serial-input');
const errorMsg = document.getElementById('error-msg');
const btnActivate = document.getElementById('btn-activate');
const btnQuit = document.getElementById('btn-quit');

let machineId = '…';

(async () => {
  machineId = await window.vt.getMachineId();
  machineIdEl.textContent = machineId;
})();

btnCopy.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(machineId);
    btnCopy.textContent = 'Kopyalandı';
    setTimeout(() => { btnCopy.textContent = 'Kopyala'; }, 1500);
  } catch (_) {}
});

btnActivate.addEventListener('click', async () => {
  errorMsg.classList.add('hidden');
  const serial = serialInput.value.trim();
  if (!serial) {
    errorMsg.textContent = 'Lisans anahtarı boş olamaz.';
    errorMsg.classList.remove('hidden');
    return;
  }
  btnActivate.disabled = true;
  btnActivate.textContent = 'Doğrulanıyor…';
  try {
    const ok = await window.vt.activateLicense(serial);
    if (ok) {
      btnActivate.textContent = '✓ Etkinleştirildi';
      // Brief success flash before main app boot
      setTimeout(() => window.vt.licenseAccepted(), 400);
    } else {
      errorMsg.textContent = 'Geçersiz lisans anahtarı (bu makine için doğru olmayabilir).';
      errorMsg.classList.remove('hidden');
      btnActivate.disabled = false;
      btnActivate.textContent = 'Etkinleştir';
    }
  } catch (e) {
    errorMsg.textContent = 'Hata: ' + (e?.message || e);
    errorMsg.classList.remove('hidden');
    btnActivate.disabled = false;
    btnActivate.textContent = 'Etkinleştir';
  }
});

btnQuit.addEventListener('click', () => window.vt.licenseQuit());

// Allow Enter to activate
serialInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') btnActivate.click();
});
