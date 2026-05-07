const fromEl = document.getElementById('from-version');
const toEl = document.getElementById('to-version');
const notesBlock = document.getElementById('notes-block');
const notesEl = document.getElementById('notes');
const btnInstall = document.getElementById('btn-install');
const btnPostpone = document.getElementById('btn-postpone');

(async () => {
  const info = await window.vt.getUpdateInfo();
  fromEl.textContent = `v${info.currentVersion}`;
  toEl.textContent = `v${info.newVersion}`;
  if (info.releaseNotes && String(info.releaseNotes).trim()) {
    notesEl.textContent = String(info.releaseNotes).trim();
    notesBlock.classList.remove('hidden');
  }
})();

btnInstall.addEventListener('click', () => {
  btnInstall.disabled = true;
  btnPostpone.disabled = true;
  btnInstall.textContent = 'Yükleniyor…';
  window.vt.updateInstall();
});

btnPostpone.addEventListener('click', () => {
  window.vt.updatePostpone();
});

// ESC = postpone (graceful exit if anything goes wrong)
window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') window.vt.updatePostpone();
});
