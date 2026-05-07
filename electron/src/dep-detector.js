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
  const ok = fs.existsSync(paths.venvPython());
  return {
    id: 'venv',
    label: 'Python venv (sanal ortam)',
    status: ok ? 'ok' : 'missing',
    detail: ok ? paths.venvPython() : 'kurulacak',
  };
}

async function detectPipPackages() {
  if (!fs.existsSync(paths.venvPython())) {
    return { id: 'pip', label: 'Python paketleri', status: 'missing', detail: 'venv yok' };
  }
  const probe = `import flask, playwright, feedparser, trafilatura, sqlalchemy, jinja2, ffmpeg, apscheduler, googleapiclient; print("ok")`;
  const r = await execP(paths.venvPython(), ['-c', probe]);
  if (!r.err && r.stdout.includes('ok')) {
    return { id: 'pip', label: 'Python paketleri', status: 'ok' };
  }
  return { id: 'pip', label: 'Python paketleri', status: 'missing', detail: 'pip install gerek' };
}

async function detectPlaywrightChromium() {
  if (!fs.existsSync(paths.venvPython())) {
    return { id: 'chromium', label: 'Playwright Chromium', status: 'missing', detail: 'venv yok' };
  }
  const r = await execP(paths.venvPython(), ['-m', 'playwright', 'install', '--dry-run', 'chromium']);
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
