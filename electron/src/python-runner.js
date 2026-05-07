const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const http = require('node:http');
const paths = require('./paths');
const log = require('./logger');

let child = null;
let chosenPort = null;

const DEFAULT_PORT = 5005;
const PORT_SCAN_RANGE = 20;       // try 5005..5024

async function findFreePort(startPort = DEFAULT_PORT) {
  for (let p = startPort; p < startPort + PORT_SCAN_RANGE; p++) {
    const free = await new Promise((resolve) => {
      const s = net.createServer();
      s.once('error', () => resolve(false));
      s.once('listening', () => s.close(() => resolve(true)));
      s.listen(p, '127.0.0.1');
    });
    if (free) return p;
  }
  throw new Error(`no free port in ${startPort}..${startPort + PORT_SCAN_RANGE}`);
}

function pythonExe() {
  return fs.existsSync(paths.venvPython()) ? paths.venvPython() : paths.embeddedPython();
}

function buildEnv(port) {
  const env = { ...process.env };
  // shortBotSrc FIRST (always-current after updates) then sitePackages (for deps)
  const parts = [paths.shortBotSrc(), paths.sitePackagesDir()];
  if (env.PYTHONPATH) parts.push(env.PYTHONPATH);
  env.PYTHONPATH = parts.join(';');
  env.SHORT_BOT_PORT = String(port);
  if (fs.existsSync(paths.ffmpegBin())) {
    env.PATH = `${path.dirname(paths.ffmpegBin())};${env.PATH ?? ''}`;
  }
  env.SHORT_BOT_CONFIG_DIR = paths.configDir();
  env.SHORT_BOT_DATA_DIR = paths.dataDir();
  env.SHORT_BOT_LOGS_DIR = paths.logsDir();
  env.SHORT_BOT_OUTPUT_ROOT = paths.outputDir();
  return env;
}

async function probeHealthz(port, timeoutMs = 30000, intervalMs = 500) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const ok = await new Promise((resolve) => {
      const req = http.get({ host: '127.0.0.1', port, path: '/healthz', timeout: 1500 }, (res) => {
        if (res.statusCode === 200) resolve(true);
        else resolve(false);
        res.resume();
      });
      req.on('error', () => resolve(false));
      req.on('timeout', () => { req.destroy(); resolve(false); });
    });
    if (ok) return true;
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return false;
}

async function start() {
  if (child) {
    log.warn('python-runner: start() called but child already running');
    return chosenPort;
  }

  chosenPort = await findFreePort();
  log.info(`python-runner: chosen port ${chosenPort}`);

  const py = pythonExe();
  const args = ['-m', 'short_bot', 'web', '--port', String(chosenPort)];
  const env = buildEnv(chosenPort);
  log.info(`python-runner: spawn ${py} ${args.join(' ')}`);

  // Ensure log dir exists (caller may not have created it yet in this dispatch)
  fs.mkdirSync(paths.logsDir(), { recursive: true });
  const stdoutLog = fs.createWriteStream(path.join(paths.logsDir(), 'panel_stdout.log'), { flags: 'a' });
  const stderrLog = fs.createWriteStream(path.join(paths.logsDir(), 'panel_stderr.log'), { flags: 'a' });

  child = spawn(py, args, {
    env,
    cwd: paths.shortBotRoot(),
    windowsHide: true,
  });
  child.stdout.pipe(stdoutLog);
  child.stderr.pipe(stderrLog);
  child.on('exit', (code, signal) => {
    try { stdoutLog.end(); } catch (_) {}
    try { stderrLog.end(); } catch (_) {}
    log.warn(`python-runner: child exit code=${code} signal=${signal}`);
    child = null;
  });

  const ready = await probeHealthz(chosenPort);
  if (!ready) {
    log.error('python-runner: healthz probe timeout');
    await stop();
    throw new Error('Flask did not become ready within 30s');
  }
  log.info('python-runner: healthz OK');
  return chosenPort;
}

async function stop() {
  if (!child) return;
  log.info('python-runner: stopping child');
  return new Promise((resolve) => {
    const c = child;
    let done = false;
    const finish = () => { if (!done) { done = true; child = null; resolve(); } };
    c.once('exit', finish);
    try { c.kill('SIGTERM'); } catch (_) {}
    setTimeout(() => {
      if (!done) {
        try { c.kill('SIGKILL'); } catch (_) {}
        setTimeout(finish, 2000);
      }
    }, 5000);
  });
}

function port() { return chosenPort; }
function isRunning() { return child !== null; }

module.exports = { start, stop, port, isRunning, findFreePort };
