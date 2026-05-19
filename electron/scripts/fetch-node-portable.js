#!/usr/bin/env node
/**
 * Download the Node.js Windows portable Zip into electron/cache/node-portable
 * so electron-builder can bundle it as extraResources. Pattern mirrors
 * fetch-python-embed.js — same download/extract/cache flow.
 *
 * The bundled Node enables Remotion rendering from the installed Electron app
 * without requiring the user to install Node.js separately. node_modules for
 * the remotion/ subproject is NOT bundled (would add ~500 MB); the Python
 * side runs `npm install` once on first Remotion render via
 * short_bot.remotion_renderer.ensure_remotion_installed.
 */
const fs = require('node:fs');
const fsp = require('node:fs/promises');
const path = require('node:path');
const https = require('node:https');
const { execSync } = require('node:child_process');

// Node 20 LTS — matches Remotion 4.x minimum and is a long-term stable release.
const NODE_VERSION = '20.18.1';
const URL = `https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-win-x64.zip`;
const cacheDir = path.resolve(__dirname, '..', 'cache');
const zipPath = path.join(cacheDir, `node-v${NODE_VERSION}-win-x64.zip`);
const outDir = path.join(cacheDir, 'node-portable');

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

  if (fs.existsSync(path.join(outDir, 'node.exe'))) {
    console.log('Node portable already cached at', outDir);
    return;
  }

  if (!fs.existsSync(zipPath)) {
    console.log(`Downloading Node ${NODE_VERSION} portable from ${URL}…`);
    await download(URL, zipPath);
    console.log('\nDownloaded.');
  } else {
    console.log('Using cached zip:', zipPath);
  }

  console.log('Extracting…');
  await fsp.rm(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  const tmpExtract = path.join(cacheDir, '_node-extract-tmp');
  await fsp.rm(tmpExtract, { recursive: true, force: true });
  fs.mkdirSync(tmpExtract, { recursive: true });
  execSync(
    `powershell -NoProfile -NonInteractive -Command "Expand-Archive -Path '${zipPath}' -DestinationPath '${tmpExtract}' -Force"`,
    { stdio: 'inherit' },
  );

  // The Zip contains a single top-level folder node-vX.Y.Z-win-x64/ — we
  // flatten one level so outDir directly contains node.exe + npx.cmd + npm.cmd.
  const inner = path.join(tmpExtract, `node-v${NODE_VERSION}-win-x64`);
  if (!fs.existsSync(inner)) {
    throw new Error(`Expected ${inner} after extraction but it does not exist`);
  }
  for (const entry of fs.readdirSync(inner)) {
    fs.renameSync(path.join(inner, entry), path.join(outDir, entry));
  }
  await fsp.rm(tmpExtract, { recursive: true, force: true });

  console.log('Node portable ready at:', outDir);
  console.log('  node.exe   :', path.join(outDir, 'node.exe'));
  console.log('  npx.cmd    :', path.join(outDir, 'npx.cmd'));
  console.log('  npm.cmd    :', path.join(outDir, 'npm.cmd'));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
