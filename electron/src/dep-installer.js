const { spawn } = require('child_process');
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const https = require('node:https');
const crypto = require('node:crypto');
const paths = require('./paths');
const log = require('./logger');

/**
 * Run a child process and stream lines to onProgress(line).
 * Resolves when exit code === 0, rejects otherwise.
 */
function runStream(cmd, args, { cwd, env, onProgress } = {}) {
  return new Promise((resolve, reject) => {
    log.info(`installer: ${cmd} ${args.join(' ')}`);
    const child = spawn(cmd, args, { cwd, env: env ?? process.env, windowsHide: true });
    let buf = '';
    const flush = (chunk) => {
      buf += chunk.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) {
        if (line.trim()) {
          log.debug('  >', line);
          onProgress?.(line);
        }
      }
    };
    child.stdout.on('data', flush);
    child.stderr.on('data', flush);
    child.on('exit', (code) => {
      if (buf.trim()) onProgress?.(buf);
      if (code === 0) resolve();
      else reject(new Error(`${cmd} exited with code ${code}`));
    });
    child.on('error', reject);
  });
}

async function installVenv({ onProgress } = {}) {
  if (fs.existsSync(paths.venvPython())) {
    onProgress?.('venv zaten mevcut, atlanıyor');
    return;
  }
  await runStream(paths.embeddedPython(), ['-m', 'venv', paths.venvDir()], { onProgress });
  // pip kurulu değilse get-pip ile manuel kur (embed Python pth düzeltmesinden sonra olabilir)
  const havePip = fs.existsSync(paths.venvPip());
  if (!havePip) {
    onProgress?.('venv pip bulunamadı, get-pip indiriliyor');
    const tmpDir = path.join(paths.userData(), 'tmp');
    fs.mkdirSync(tmpDir, { recursive: true });
    const getPip = path.join(tmpDir, 'get-pip.py');
    await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPip, { onProgress });
    await runStream(paths.venvPython(), [getPip], { onProgress });
  }
}

async function installPipPackages({ onProgress } = {}) {
  // pip install -e {shortBotRoot} → uses pyproject.toml in resources/short-bot/
  const args = ['-m', 'pip', 'install', '-e', paths.shortBotRoot(), '--upgrade', '--no-warn-script-location'];
  try {
    await runStream(paths.venvPython(), args, { onProgress });
  } catch (e) {
    // Fallback: prefer prebuilt wheels (avoids MSVC build for native packages)
    onProgress?.('Build hatası — prebuilt wheels deneniyor');
    await runStream(paths.venvPython(), [...args, '--only-binary=:all:'], { onProgress });
  }
}

async function installPlaywrightChromium({ onProgress } = {}) {
  const env = { ...process.env };
  // Allow mirror override (env-var) without code change
  // PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright
  let lastErr = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await runStream(paths.venvPython(), ['-m', 'playwright', 'install', 'chromium'], { env, onProgress });
      return;
    } catch (e) {
      lastErr = e;
      onProgress?.(`Deneme ${attempt}/3 başarısız: ${e.message}`);
      await new Promise((r) => setTimeout(r, 2000));
    }
  }
  throw lastErr;
}

/**
 * Download a URL to disk. Resolves on success, rejects on HTTP error or timeout.
 * Optional sha256 verifies bytes; mismatch deletes the file and rejects.
 */
function downloadFile(url, destPath, { onProgress, sha256, redirects = 5 } = {}) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, { headers: { 'User-Agent': 'VurucuTim/1.0' } }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && redirects > 0) {
        return resolve(downloadFile(res.headers.location, destPath, { onProgress, sha256, redirects: redirects - 1 }));
      }
      if (res.statusCode !== 200) {
        return reject(new Error(`HTTP ${res.statusCode} for ${url}`));
      }
      const total = parseInt(res.headers['content-length'] || '0', 10);
      let received = 0;
      let lastPct = -1;
      const file = fs.createWriteStream(destPath);
      const hasher = sha256 ? crypto.createHash('sha256') : null;
      res.on('data', (chunk) => {
        received += chunk.length;
        if (hasher) hasher.update(chunk);
        if (total) {
          const pct = Math.floor((received / total) * 100);
          if (pct !== lastPct && pct % 5 === 0) {
            onProgress?.(`İndiriliyor: ${pct}% (${(received / 1048576).toFixed(1)}/${(total / 1048576).toFixed(1)} MB)`);
            lastPct = pct;
          }
        }
      });
      res.pipe(file);
      file.on('finish', () => {
        file.close(() => {
          if (sha256) {
            const got = hasher.digest('hex');
            if (got.toLowerCase() !== sha256.toLowerCase()) {
              fs.unlinkSync(destPath);
              return reject(new Error(`SHA256 mismatch: expected ${sha256}, got ${got}`));
            }
          }
          resolve();
        });
      });
      file.on('error', reject);
    });
    req.on('error', reject);
    req.setTimeout(60000, () => req.destroy(new Error('download timeout')));
  });
}

const FFMPEG_MIRRORS = [
  // gyan.dev — official builds, no SHA pinned (URL changes per release)
  'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip',
  // BtbN GitHub releases — fallback
  'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip',
];

async function installFfmpeg({ onProgress } = {}) {
  const tmpDir = path.join(paths.userData(), 'tmp');
  fs.mkdirSync(tmpDir, { recursive: true });
  const zipPath = path.join(tmpDir, 'ffmpeg.zip');

  let downloaded = false;
  let lastErr = null;
  for (const url of FFMPEG_MIRRORS) {
    try {
      await fsp.unlink(zipPath).catch(() => {});   // clean prior partial
      onProgress?.(`ffmpeg indiriliyor: ${url}`);
      await downloadFile(url, zipPath, { onProgress });
      downloaded = true;
      break;
    } catch (e) {
      lastErr = e;
      onProgress?.(`Mirror başarısız: ${e.message}`);
    }
  }
  if (!downloaded) throw lastErr;

  onProgress?.('ZIP açılıyor');
  const ffmpegRoot = path.join(paths.depsDir(), 'ffmpeg');
  await fsp.rm(ffmpegRoot, { recursive: true, force: true });
  fs.mkdirSync(ffmpegRoot, { recursive: true });

  const extractDir = path.join(tmpDir, 'ffmpeg-extract');
  await fsp.rm(extractDir, { recursive: true, force: true });

  // Use PowerShell Expand-Archive (built into Windows)
  const psEscape = (s) => s.replace(/"/g, '""');
  await runStream('powershell', [
    '-NoProfile', '-NonInteractive',
    '-Command', `Expand-Archive -Path "${psEscape(zipPath)}" -DestinationPath "${psEscape(extractDir)}" -Force`,
  ], { onProgress });

  // The ZIP contains a top-level folder like ffmpeg-6.0-essentials_build/
  const entries = await fsp.readdir(extractDir);
  const inner = entries.find((e) => e.toLowerCase().includes('ffmpeg'));
  if (!inner) throw new Error('ffmpeg ZIP içinde ffmpeg klasörü bulunamadı');
  const innerBin = path.join(extractDir, inner, 'bin');
  if (!fs.existsSync(innerBin)) throw new Error('ffmpeg/bin klasörü bulunamadı');

  // Move bin/ → deps/ffmpeg/bin/
  await fsp.cp(path.join(extractDir, inner), ffmpegRoot, { recursive: true });
  await fsp.rm(extractDir, { recursive: true, force: true });
  await fsp.unlink(zipPath).catch(() => {});

  if (!fs.existsSync(paths.ffmpegBin())) {
    throw new Error(`ffmpeg.exe bulunamadı: ${paths.ffmpegBin()}`);
  }
  onProgress?.(`ffmpeg kuruldu: ${paths.ffmpegBin()}`);
}

async function copyExampleSettings({ onProgress } = {}) {
  if (fs.existsSync(paths.settingsYaml())) {
    onProgress?.('settings.yaml zaten mevcut, atlanıyor');
    return;
  }
  if (!fs.existsSync(paths.settingsExample())) {
    onProgress?.('UYARI: settings.yaml.example bulunamadı');
    return;
  }
  let content = await fsp.readFile(paths.settingsExample(), 'utf-8');
  // Auto-fill ffmpeg_path if installed
  if (fs.existsSync(paths.ffmpegBin())) {
    content = content.replace(
      /^ffmpeg_path:.*$/m,
      `ffmpeg_path: "${paths.ffmpegBin().replace(/\\/g, '\\\\')}"`,
    );
  }
  await fsp.writeFile(paths.settingsYaml(), content, 'utf-8');
  onProgress?.(`settings.yaml oluşturuldu: ${paths.settingsYaml()}`);
}

async function copyBundledMusic({ onProgress } = {}) {
  if (!fs.existsSync(paths.bundledMusic())) return;
  for (const mood of ['breaking', 'neutral', 'upbeat']) {
    const src = path.join(paths.bundledMusic(), mood);
    const dst = path.join(paths.musicRoot(), mood);
    fs.mkdirSync(dst, { recursive: true });
    if (!fs.existsSync(src)) continue;
    const files = await fsp.readdir(src);
    for (const f of files) {
      if (!f.toLowerCase().endsWith('.mp3')) continue;
      const target = path.join(dst, f);
      if (!fs.existsSync(target)) {
        await fsp.copyFile(path.join(src, f), target);
        onProgress?.(`Müzik kopyalandı: ${mood}/${f}`);
      }
    }
  }
}

async function initDb({ onProgress } = {}) {
  const env = {
    ...process.env,
    PYTHONPATH: paths.shortBotRoot() + (process.env.PYTHONPATH ? `;${process.env.PYTHONPATH}` : ''),
    SHORT_BOT_DATA_DIR: paths.dataDir(),
  };
  await runStream(paths.venvPython(), ['-m', 'short_bot', 'init'], {
    cwd: paths.shortBotRoot(), env, onProgress,
  });
}

async function installAll(deps, onProgress) {
  const has = (id) => deps.some((d) => d.id === id && d.status !== 'ok');
  // Order matters
  if (has('venv'))     { onProgress?.({ phase: 'venv', text: 'venv hazırlanıyor…' }); await installVenv({ onProgress: (l) => onProgress?.({ phase: 'venv', text: l }) }); }
  if (has('pip'))      { onProgress?.({ phase: 'pip', text: 'Python paketleri…' }); await installPipPackages({ onProgress: (l) => onProgress?.({ phase: 'pip', text: l }) }); }
  if (has('chromium')) { onProgress?.({ phase: 'chromium', text: 'Chromium indiriliyor…' }); await installPlaywrightChromium({ onProgress: (l) => onProgress?.({ phase: 'chromium', text: l }) }); }
  if (has('ffmpeg'))   { onProgress?.({ phase: 'ffmpeg', text: 'ffmpeg indiriliyor…' }); await installFfmpeg({ onProgress: (l) => onProgress?.({ phase: 'ffmpeg', text: l }) }); }

  onProgress?.({ phase: 'config', text: 'settings.yaml hazırlanıyor…' });
  await copyExampleSettings({ onProgress: (l) => onProgress?.({ phase: 'config', text: l }) });

  onProgress?.({ phase: 'music', text: 'Bundled müzik kopyalanıyor…' });
  await copyBundledMusic({ onProgress: (l) => onProgress?.({ phase: 'music', text: l }) });

  onProgress?.({ phase: 'db', text: 'DB başlatılıyor…' });
  await initDb({ onProgress: (l) => onProgress?.({ phase: 'db', text: l }) });
}

module.exports = {
  installVenv, installPipPackages, installPlaywrightChromium,
  installFfmpeg, copyExampleSettings, copyBundledMusic, initDb,
  installAll, downloadFile,
};
