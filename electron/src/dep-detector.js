const { execFile } = require('child_process');
const fs = require('node:fs');
const path = require('node:path');
const paths = require('./paths');

function execP(cmd, args = [], opts = {}) {
  return new Promise((resolve) => {
    execFile(cmd, args, { timeout: 10000, ...opts }, (err, stdout, stderr) => {
      resolve({ err, stdout: stdout || '', stderr: stderr || '' });
    });
  });
}

async function detectVenv() {
  // Check pip is bootstrapped into the flat site-packages dir
  const ok = fs.existsSync(path.join(paths.sitePackagesDir(), 'pip'));
  return {
    id: 'venv',
    label: 'Python ortamı (pip)',
    status: ok ? 'ok' : 'missing',
    detail: ok ? paths.sitePackagesDir() : 'kurulacak',
  };
}

async function detectPipPackages() {
  const sitePackages = paths.sitePackagesDir();
  if (!fs.existsSync(path.join(sitePackages, 'pip'))) {
    return { id: 'pip', label: 'Python paketleri', status: 'missing', detail: 'pip yok' };
  }
  const probe = `import flask, playwright, feedparser, trafilatura, sqlalchemy, jinja2, ffmpeg, apscheduler, googleapiclient; print("ok")`;
  const env = { ...process.env, PYTHONPATH: sitePackages };
  const r = await execP(paths.embeddedPython(), ['-c', probe], { env });
  if (!r.err && r.stdout.includes('ok')) {
    return { id: 'pip', label: 'Python paketleri', status: 'ok' };
  }
  return { id: 'pip', label: 'Python paketleri', status: 'missing', detail: 'pip install gerek' };
}

async function detectPlaywrightChromium() {
  const sitePackages = paths.sitePackagesDir();
  if (!fs.existsSync(path.join(sitePackages, 'pip'))) {
    return { id: 'chromium', label: 'Playwright Chromium', status: 'missing', detail: 'pip yok' };
  }
  const env = { ...process.env, PYTHONPATH: sitePackages };
  const r = await execP(paths.embeddedPython(), ['-m', 'playwright', 'install', '--dry-run', 'chromium'], { env });
  if (!r.err && /already installed|is already/i.test(r.stdout + r.stderr)) {
    return { id: 'chromium', label: 'Playwright Chromium', status: 'ok' };
  }
  return { id: 'chromium', label: 'Playwright Chromium', status: 'missing', detail: '~150MB' };
}

async function detectFfmpeg() {
  const sys = await execP('ffmpeg', ['-version']);
  if (!sys.err) {
    return { id: 'ffmpeg', label: 'ffmpeg', status: 'ok', source: 'system' };
  }
  if (fs.existsSync(paths.ffmpegBin())) {
    return { id: 'ffmpeg', label: 'ffmpeg', status: 'ok', source: 'bundled', detail: paths.ffmpegBin() };
  }
  return { id: 'ffmpeg', label: 'ffmpeg', status: 'missing', detail: '~80MB' };
}

async function detectClaudeCli() {
  const r = await execP('claude', ['--version']);
  if (!r.err) {
    return { id: 'claude-cli', label: 'Claude CLI', status: 'ok' };
  }
  return {
    id: 'claude-cli',
    label: 'Claude CLI',
    status: 'missing',
    detail: 'manuel kurulum',
    action: {
      type: 'open-url',
      url: 'https://docs.anthropic.com/claude/docs/claude-code',
      message: 'Tarayıcıda kurulum rehberi açılır. Kurduktan sonra tekrar Sağlık Kontrolü çalıştır.',
    },
  };
}

async function detectClaudeAuth() {
  const r = await execP('claude', ['--print', 'ping'], { timeout: 30000 });
  if (!r.err && (r.stdout + r.stderr).length > 0) {
    return { id: 'claude-auth', label: 'Claude oturumu', status: 'ok' };
  }
  return {
    id: 'claude-auth',
    label: 'Claude oturumu',
    status: 'warning',
    detail: 'manuel `claude login` gerekebilir',
    action: { type: 'shell-instruction', command: 'claude login' },
  };
}

async function detectAll() {
  return Promise.all([
    detectVenv(),
    detectPipPackages(),
    detectPlaywrightChromium(),
    detectFfmpeg(),
    detectClaudeCli(),
    detectClaudeAuth(),
  ]);
}

module.exports = {
  detectVenv, detectPipPackages, detectPlaywrightChromium,
  detectFfmpeg, detectClaudeCli, detectClaudeAuth, detectAll,
};
