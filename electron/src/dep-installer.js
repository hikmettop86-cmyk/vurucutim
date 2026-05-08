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
 *
 * On non-zero exit, the rejected Error gets a `.tail` property containing the
 * last N stdout/stderr lines (default 80) and `.exitCode`. Callers can attach
 * the tail to user-facing error messages so the wizard shows the real failure
 * (e.g. pip's ResolutionImpossible block) instead of just "exited with code 1".
 */
function runStream(cmd, args, { cwd, env, onProgress, tailLines = 80 } = {}) {
  return new Promise((resolve, reject) => {
    log.info(`installer: ${cmd} ${args.join(' ')}`);
    const child = spawn(cmd, args, { cwd, env: env ?? process.env, windowsHide: true });
    let buf = '';
    const tail = []; // ring buffer of recent lines
    const pushTail = (line) => {
      tail.push(line);
      if (tail.length > tailLines) tail.shift();
    };
    const flush = (chunk) => {
      buf += chunk.toString();
      const lines = buf.split(/\r?\n/);
      buf = lines.pop();
      for (const line of lines) {
        if (line.trim()) {
          log.debug('  >', line);
          pushTail(line);
          onProgress?.(line);
        }
      }
    };
    child.stdout.on('data', flush);
    child.stderr.on('data', flush);
    child.on('exit', (code) => {
      if (buf.trim()) {
        pushTail(buf);
        onProgress?.(buf);
      }
      if (code === 0) {
        resolve();
      } else {
        const err = new Error(`${cmd} exited with code ${code}`);
        err.exitCode = code;
        err.tail = tail.join('\n');
        reject(err);
      }
    });
    child.on('error', reject);
  });
}

async function installVenv({ onProgress } = {}) {
  // Embedded Python lacks `venv` module. Instead bootstrap pip into a flat
  // --target site-packages dir and use that for all subsequent installs.
  const sitePackages = paths.sitePackagesDir();
  fs.mkdirSync(sitePackages, { recursive: true });

  const pipPkg = path.join(sitePackages, 'pip');
  if (fs.existsSync(pipPkg)) {
    onProgress?.('pip zaten mevcut, atlanıyor');
    return;
  }

  onProgress?.('get-pip.py indiriliyor');
  const tmpDir = path.join(paths.userData(), 'tmp');
  fs.mkdirSync(tmpDir, { recursive: true });
  const getPip = path.join(tmpDir, 'get-pip.py');
  await downloadFile('https://bootstrap.pypa.io/get-pip.py', getPip, { onProgress });

  onProgress?.('pip kuruluyor (--target)');
  await runStream(paths.embeddedPython(), [
    getPip,
    `--target=${sitePackages}`,
    '--no-warn-script-location',
    '--no-cache-dir',
  ], {
    env: { ...process.env, PYTHONPATH: sitePackages },
    onProgress,
  });
}

async function installPipPackages({ onProgress } = {}) {
  // We CANNOT pip-install short-bot itself: its source lives under read-only
  // `Program Files` and pip needs to write `egg-info` there. Instead, parse
  // pyproject.toml ourselves and install only the dependencies. short_bot is
  // imported via PYTHONPATH = shortBotSrc + sitePackages (set in python-runner).
  const sitePackages = paths.sitePackagesDir();
  const pyproject = path.join(paths.shortBotRoot(), 'pyproject.toml');
  if (!fs.existsSync(pyproject)) {
    throw new Error(`pyproject.toml bulunamadı: ${pyproject}`);
  }

  // Use embedded Python's tomllib to read deps (avoid pulling in JS toml lib).
  const readDepsScript = `
import tomllib, json, sys
with open(r'${pyproject.replace(/\\/g, '\\\\')}', 'rb') as f:
    data = tomllib.load(f)
deps = data.get('project', {}).get('dependencies', [])
print(json.dumps(deps))
`;
  const readEnv = { ...process.env, PYTHONPATH: sitePackages };
  const { execFile } = require('child_process');
  const deps = await new Promise((resolve, reject) => {
    execFile(paths.embeddedPython(), ['-c', readDepsScript], { env: readEnv, timeout: 15000 }, (err, stdout, stderr) => {
      if (err) return reject(new Error(`pyproject.toml okunamadı: ${stderr || err.message}`));
      try { resolve(JSON.parse(stdout.trim())); }
      catch (e) { reject(new Error(`Geçersiz JSON: ${stdout}`)); }
    });
  });
  if (!Array.isArray(deps) || deps.length === 0) {
    throw new Error('pyproject.toml içinde [project].dependencies bulunamadı');
  }
  onProgress?.(`pyproject.toml: ${deps.length} bağımlılık tespit edildi`);

  const baseArgs = [
    '-m', 'pip', 'install',
    `--target=${sitePackages}`,
    '--no-warn-script-location',
  ];
  const env = { ...process.env, PYTHONPATH: sitePackages };

  // Tier 1: --upgrade + --prefer-binary. Mevcut yarım install kalıntısı varsa
  // (örn. pydantic var ama pydantic_core yok) --upgrade onları taze indirip
  // transitive eksikleri çözer. v0.1.30→0.1.31'de --upgrade kaldırılmıştı,
  // sonuçta kullanıcılar "ModuleNotFoundError: pydantic_core" alıyordu.
  let tier1Err = null;
  try {
    await runStream(paths.embeddedPython(), [...baseArgs, '--upgrade', '--prefer-binary', ...deps], {
      env, onProgress,
    });
  } catch (e) {
    tier1Err = e;
    const msg = (e.tail || e.message || '').slice(0, 4000);
    onProgress?.(`Tier 1 başarısız (${e.exitCode || '?'}): ${msg.split('\n').slice(-3).join(' | ')}`);
    if (!/ResolutionImpossible|conflict|incompatible/i.test(msg)) {
      // Build/network error — Tier 2: only-binary fallback
      onProgress?.('Tier 2: prebuilt-only deneniyor');
      try {
        await runStream(paths.embeddedPython(), [...baseArgs, '--upgrade', '--prefer-binary', '--only-binary=:all:', ...deps], {
          env, onProgress,
        });
        tier1Err = null;
      } catch (e2) {
        onProgress?.(`Tier 2 da başarısız: ${(e2.tail || e2.message || '').split('\n').slice(-3).join(' | ')}`);
      }
    }
  }

  // Tier 3: per-package --no-deps (resolver tamamen bypass). Sadece tier1+2 fail
  // ettiğinde; başarılıysa atla.
  if (tier1Err) {
    onProgress?.('Tier 3: paketler tek tek kuruluyor (--no-deps)');
    const failed = [];
    for (const dep of deps) {
      try {
        await runStream(paths.embeddedPython(), [
          ...baseArgs, '--upgrade', '--prefer-binary', '--no-deps', dep,
        ], { env, onProgress });
      } catch (e) {
        failed.push(`${dep}: ${(e.tail || e.message || '').split('\n').slice(-2).join(' / ')}`);
      }
    }
    if (failed.length > 0) {
      const summary = failed.slice(0, 10).join('\n');
      const err = new Error(`pip Tier 3 — ${failed.length} paket başarısız:\n${summary}`);
      err.tail = summary;
      throw err;
    }
  }

  // SMOKE TEST + AUTO-REPAIR
  // pip "Successfully installed" demesi yetmez — kısmi install kalıntısı
  // (örn. v0.1.31'in yarım kurulumu) bazı submodule'leri eksik bırakabiliyor
  // (en sık fail eden: pydantic_core). Kritik importları test et, fail ederse
  // o paketleri --force-reinstall ile yeniden kur.
  await _verifyAndRepair(env, onProgress);
}

async function _verifyAndRepair(env, onProgress, attempt = 1) {
  const sitePackages = paths.sitePackagesDir();
  // pyproject'ten import edilebilir-olması-gereken kritik modüller. Listede
  // hem ana paket hem binary core (pydantic_core) hem framework var ki
  // herhangi bir partial install izi yakalanabilsin.
  const critical = [
    'pydantic', 'pydantic_core', 'sqlalchemy', 'flask',
    'jinja2', 'requests', 'yaml', 'PIL',
    'cryptography', 'google.auth', 'googleapiclient',
    'feedparser', 'trafilatura', 'playwright', 'apscheduler',
  ];
  // importlib.import_module submodule'leri (örn. google.auth) doğru yükler;
  // __import__ sadece root'u getiriyor — submodule'deki ImportError'ları kaçırır.
  const probe = `import importlib\nfor m in ${JSON.stringify(critical)}:\n    try: importlib.import_module(m)\n    except Exception as e: print('MISSING:'+m+':'+type(e).__name__+':'+str(e)[:120])\n`;
  const { execFile } = require('child_process');
  const result = await new Promise((resolve) => {
    execFile(paths.embeddedPython(), ['-c', probe], { env, timeout: 30000 },
      (err, stdout, stderr) => resolve({ err, stdout: stdout || '', stderr: stderr || '' }));
  });
  const missing = (result.stdout + result.stderr)
    .split(/\r?\n/)
    .filter((l) => l.startsWith('MISSING:'))
    .map((l) => l.split(':')[1]);

  if (missing.length === 0) {
    onProgress?.('Smoke test OK: kritik paketler import edilebiliyor');
    return;
  }

  if (attempt > 2) {
    const err = new Error(`Smoke test ${attempt} denemeden sonra hala fail: ${missing.join(', ')}\n${result.stdout}\n${result.stderr}`);
    err.tail = err.message;
    throw err;
  }

  // Repair: pydantic_core gibi binary deps için pydantic'i force-reinstall
  // (transitive olarak pydantic_core'u getirir). pydantic_core'un doğrudan
  // wheel'i Windows için pip cache'inden alınamayabiliyor, bu yüzden
  // pydantic ile birlikte ZORLA yeniden indir.
  onProgress?.(`Smoke test ${missing.length} eksik tespit etti: ${missing.join(', ')} — repair başlıyor`);

  // Eksik modülün hangi paketten geldiğini map et
  const moduleToPackage = {
    pydantic: 'pydantic',
    pydantic_core: 'pydantic',     // binary core, pydantic ile gelir
    sqlalchemy: 'sqlalchemy',
    flask: 'flask',
    jinja2: 'jinja2',
    requests: 'requests',
    yaml: 'pyyaml',
    PIL: 'pillow',
    cryptography: 'cryptography',
    'google.auth': 'google-auth',
    googleapiclient: 'google-api-python-client',
    feedparser: 'feedparser',
    trafilatura: 'trafilatura',
    playwright: 'playwright',
    apscheduler: 'apscheduler',
  };
  const packagesToRepair = [...new Set(missing.map((m) => moduleToPackage[m]).filter(Boolean))];

  await runStream(paths.embeddedPython(), [
    '-m', 'pip', 'install',
    `--target=${sitePackages}`,
    '--upgrade', '--force-reinstall', '--prefer-binary',
    '--no-warn-script-location',
    ...packagesToRepair,
  ], { env, onProgress });

  // Recurse — yeni denemede smoke test yine yapılır
  return _verifyAndRepair(env, onProgress, attempt + 1);
}

async function installPlaywrightChromium({ onProgress } = {}) {
  const env = { ...process.env, PYTHONPATH: paths.sitePackagesDir() };
  let lastErr = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      await runStream(paths.embeddedPython(), ['-m', 'playwright', 'install', 'chromium'], { env, onProgress });
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

async function copyTemplates({ onProgress } = {}) {
  // Copy bundled templates/ to user-data templates/.
  // Strategy:
  //   - Top-level *.html.j2 (archetype templates) → ALWAYS overwrite with bundled version.
  //     Reason: these are app-shipped defaults; user does not edit them, but bundled
  //     versions improve across releases (font tweaks, line-clamp adjustments, etc.).
  //   - css/ subdir (per-channel CSS, runtime-generated by channel_new/edit) → preserve;
  //     copy missing files only. User-generated CSS is never overwritten.
  const src = paths.bundledTemplates();
  const dst = paths.templatesDir();
  if (!fs.existsSync(src)) {
    onProgress?.('UYARI: bundled templates bulunamadı');
    return;
  }
  fs.mkdirSync(dst, { recursive: true });

  const entries = await fsp.readdir(src, { withFileTypes: true });
  for (const e of entries) {
    const s = path.join(src, e.name);
    const d = path.join(dst, e.name);
    if (e.isDirectory()) {
      // Subdirs (mainly css/): preserve user-generated files
      fs.mkdirSync(d, { recursive: true });
      await copyDirIfMissing(s, d, onProgress);
    } else {
      // Top-level files (j2 templates): always overwrite to apply bundled improvements
      await fsp.copyFile(s, d);
      onProgress?.(`template güncellendi: ${e.name}`);
    }
  }
  onProgress?.(`templates hazır: ${dst}`);
}

async function copyDirIfMissing(srcDir, dstDir, onProgress) {
  const entries = await fsp.readdir(srcDir, { withFileTypes: true });
  for (const e of entries) {
    const s = path.join(srcDir, e.name);
    const d = path.join(dstDir, e.name);
    if (e.isDirectory()) {
      fs.mkdirSync(d, { recursive: true });
      await copyDirIfMissing(s, d, onProgress);
    } else {
      if (!fs.existsSync(d)) {
        await fsp.copyFile(s, d);
      }
    }
  }
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
  const parts = [paths.shortBotSrc(), paths.sitePackagesDir()];
  if (process.env.PYTHONPATH) parts.push(process.env.PYTHONPATH);
  const env = {
    ...process.env,
    PYTHONPATH: parts.join(';'),
    SHORT_BOT_DATA_DIR: paths.dataDir(),
    SHORT_BOT_CONFIG_DIR: paths.configDir(),
  };
  // Explicit --db-path because the CLI default is cwd-relative; cwd is read-only
  // when installed to Program Files. dataDir() is under %LOCALAPPDATA% (writable).
  fs.mkdirSync(paths.dataDir(), { recursive: true });
  const dbPath = path.join(paths.dataDir(), 'short_bot.sqlite');
  await runStream(paths.embeddedPython(), ['-m', 'short_bot', 'init', '--db-path', dbPath], {
    cwd: paths.shortBotRoot(), env, onProgress,
  });
}

// Per-step user-facing labels and troubleshooting hints, surfaced when an
// installer step throws. Helps the user identify the failing phase + what to
// try next without diving into log files.
const STEP_HINTS = {
  venv: {
    label: 'pip bootstrap (get-pip)',
    hint: 'İnternet bağlantısı veya antivirüs https://bootstrap.pypa.io adresini engelliyor olabilir.',
  },
  pip: {
    label: 'Python paketleri (pyproject deps)',
    hint: 'Microsoft Defender pip download/derleme adımlarını blokluyor olabilir. Antivirüs istisnası ekleyin: %LOCALAPPDATA%\\VurucuTim\\python-site-packages',
  },
  chromium: {
    label: 'Playwright Chromium (~150MB)',
    hint: 'Chromium CDN engellenmiş veya disk dolu olabilir. cdn.playwright.dev erişimini kontrol edin.',
  },
  ffmpeg: {
    label: 'ffmpeg (~80MB)',
    hint: 'gyan.dev veya github.com/BtbN/FFmpeg-Builds engelleniyor olabilir.',
  },
  config: {
    label: 'Ayarlar (settings.yaml + templates)',
    hint: 'Klasör izinleri: %LOCALAPPDATA%\\VurucuTim\\ klasörüne yazma izni gerek.',
  },
  music: {
    label: 'Bundled müzik kopyası',
    hint: 'Klasör izinleri sorunu olabilir.',
  },
  db: {
    label: 'Veritabanı başlatma (SQLite)',
    hint: 'short_bot Python paketi düzgün yüklenmemiş olabilir; pip adımı başarılı oldu mu kontrol edin.',
  },
};

function _wrapStepError(stepId, originalError) {
  const meta = STEP_HINTS[stepId] || { label: stepId, hint: '' };
  const origMsg = (originalError && originalError.message) || String(originalError);
  const tail = (originalError && originalError.tail) || '';
  // Asıl hata genelde tail'in son ~30 satırında — onu öne koy. Dev mesajı
  // ("python.exe exited with code 1") tek başına faydasız.
  const tailTrim = tail.length > 1500
    ? '…\n' + tail.slice(tail.length - 1500)
    : tail;
  const logPath = path.join(paths.logsDir(), 'electron-main.log');
  const lines = [
    `[${meta.label}] başarısız (exit ${originalError?.exitCode ?? '?'})`,
    '',
    'HATA ÇIKTISI (son satırlar):',
    tailTrim || origMsg,
    '',
    `İpucu: ${meta.hint}`,
    '',
    `Tam log: ${logPath}`,
  ];
  const e = new Error(lines.join('\n'));
  e.stepId = stepId;
  e.originalError = origMsg;
  e.tail = tail;
  e.logPath = logPath;
  return e;
}

async function _runStep(deps, onProgress, stepId, label, fn) {
  if (!deps) {
    // Mandatory step (config/music/db) — always run
  } else {
    const has = deps.some((d) => d.id === stepId && d.status !== 'ok');
    if (!has) return;
  }
  onProgress?.({ phase: stepId, text: `${label} başlıyor…` });
  try {
    await fn();
  } catch (err) {
    throw _wrapStepError(stepId, err);
  }
}

async function installAll(deps, onProgress) {
  // Each step is wrapped so a failure surfaces the exact phase + hint to the user.
  await _runStep(deps, onProgress, 'venv', 'pip bootstrap',
    () => installVenv({ onProgress: (l) => onProgress?.({ phase: 'venv', text: l }) }));
  await _runStep(deps, onProgress, 'pip', 'Python paketleri',
    () => installPipPackages({ onProgress: (l) => onProgress?.({ phase: 'pip', text: l }) }));
  await _runStep(deps, onProgress, 'chromium', 'Chromium',
    () => installPlaywrightChromium({ onProgress: (l) => onProgress?.({ phase: 'chromium', text: l }) }));
  await _runStep(deps, onProgress, 'ffmpeg', 'ffmpeg',
    () => installFfmpeg({ onProgress: (l) => onProgress?.({ phase: 'ffmpeg', text: l }) }));

  // Mandatory bootstrap steps (always run, no `deps` filter)
  await _runStep(null, onProgress, 'config', 'settings.yaml',
    () => copyExampleSettings({ onProgress: (l) => onProgress?.({ phase: 'config', text: l }) }));
  await _runStep(null, onProgress, 'config', 'Templates',
    () => copyTemplates({ onProgress: (l) => onProgress?.({ phase: 'config', text: l }) }));
  await _runStep(null, onProgress, 'music', 'Bundled müzik',
    () => copyBundledMusic({ onProgress: (l) => onProgress?.({ phase: 'music', text: l }) }));
  await _runStep(null, onProgress, 'db', 'Veritabanı',
    () => initDb({ onProgress: (l) => onProgress?.({ phase: 'db', text: l }) }));
}

module.exports = {
  installVenv, installPipPackages, installPlaywrightChromium,
  installFfmpeg, copyExampleSettings, copyTemplates, copyBundledMusic, initDb,
  installAll, downloadFile,
};
