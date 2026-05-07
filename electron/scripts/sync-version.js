#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');

const electronPkg = path.resolve(__dirname, '..', 'package.json');
const pyproject = path.resolve(__dirname, '..', '..', 'pyproject.toml');

function readJson(p) { return JSON.parse(fs.readFileSync(p, 'utf-8')); }
function writeJson(p, o) { fs.writeFileSync(p, JSON.stringify(o, null, 2) + '\n', 'utf-8'); }

function readPyVersion() {
  const txt = fs.readFileSync(pyproject, 'utf-8');
  const m = txt.match(/^version\s*=\s*"([^"]+)"/m);
  if (!m) throw new Error('pyproject.toml: version not found');
  return m[1];
}

function writePyVersion(v) {
  let txt = fs.readFileSync(pyproject, 'utf-8');
  txt = txt.replace(/^version\s*=\s*"[^"]+"/m, `version = "${v}"`);
  fs.writeFileSync(pyproject, txt, 'utf-8');
}

const pkg = readJson(electronPkg);
const pyVer = readPyVersion();

if (pkg.version === pyVer) {
  console.log(`Versions in sync: ${pkg.version}`);
  process.exit(0);
}

// Take the higher version (semver-ish)
function cmp(a, b) {
  const pa = a.split('.').map((n) => parseInt(n, 10));
  const pb = b.split('.').map((n) => parseInt(n, 10));
  for (let i = 0; i < 3; i++) {
    if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) - (pb[i] || 0);
  }
  return 0;
}

if (cmp(pkg.version, pyVer) > 0) {
  console.log(`pyproject.toml: ${pyVer} → ${pkg.version}`);
  writePyVersion(pkg.version);
} else {
  console.log(`electron/package.json: ${pkg.version} → ${pyVer}`);
  pkg.version = pyVer;
  writeJson(electronPkg, pkg);
}
