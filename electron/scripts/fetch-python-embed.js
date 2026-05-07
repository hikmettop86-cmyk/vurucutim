#!/usr/bin/env node
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const https = require('node:https');
const { execSync } = require('node:child_process');

const PYTHON_VERSION = '3.11.9';
const URL = `https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip`;
const cacheDir = path.resolve(__dirname, '..', 'cache');
const zipPath = path.join(cacheDir, `python-${PYTHON_VERSION}-embed.zip`);
const outDir = path.join(cacheDir, 'python-embed');

function download(url, dest) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(dest);
    https.get(url, (res) => {
      if (res.statusCode === 302 || res.statusCode === 301) {
        file.close();
        fs.unlinkSync(dest);
        return resolve(download(res.headers.location, dest));
      }
      if (res.statusCode !== 200) return reject(new Error(`HTTP ${res.statusCode}`));
      const total = parseInt(res.headers['content-length'] || '0', 10);
      let received = 0;
      let lastPct = -1;
      res.on('data', (c) => {
        received += c.length;
        if (total) {
          const pct = Math.floor((received / total) * 100);
          if (pct !== lastPct && pct % 10 === 0) {
            process.stdout.write(`  ${pct}%\r`);
            lastPct = pct;
          }
        }
      });
      res.pipe(file);
      file.on('finish', () => file.close(resolve));
      file.on('error', reject);
    }).on('error', reject);
  });
}

async function main() {
  fs.mkdirSync(cacheDir, { recursive: true });

  if (fs.existsSync(path.join(outDir, 'python.exe'))) {
    console.log('Python embeddable already cached at', outDir);
    return;
  }

  if (!fs.existsSync(zipPath)) {
    console.log(`Downloading Python ${PYTHON_VERSION} embeddable from ${URL}…`);
    await download(URL, zipPath);
    console.log('\nDownloaded.');
  } else {
    console.log('Using cached zip:', zipPath);
  }

  console.log('Extracting…');
  await fsp.rm(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  execSync(
    `powershell -NoProfile -NonInteractive -Command "Expand-Archive -Path '${zipPath}' -DestinationPath '${outDir}' -Force"`,
    { stdio: 'inherit' },
  );

  // REMOVE python311._pth — its presence forces "isolated mode" which ignores
  // PYTHONPATH and site.py. We need both for our --target site-packages strategy.
  // Without _pth, embedded Python falls back to normal sys.path behavior:
  //   - python311.zip is still auto-added (stdlib stays accessible)
  //   - PYTHONPATH env var is honored
  //   - site.py runs (so .pth files inside site-packages are processed)
  const pthFile = path.join(outDir, 'python311._pth');
  if (fs.existsSync(pthFile)) {
    fs.unlinkSync(pthFile);
    console.log('Removed python311._pth (PYTHONPATH + site.py now active).');
  }

  console.log('Python embeddable ready at:', outDir);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
