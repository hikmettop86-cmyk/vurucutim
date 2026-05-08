// Offline HMAC-signed license validation.
//
// Format: VRCT-XXXX-XXXX-XXXX-XXXX  (16 chars = 16 base32 chars after prefix)
// Body = base32( HMAC-SHA256(SECRET, machineId)[:10] )
//
// Machine ID = base32( SHA256(volume_serial + motherboard_uuid)[:8] )
//
// Validate: recompute body from machineId, constant-time compare with input.

const crypto = require('node:crypto');
const { execSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const paths = require('./paths');

// Embedded secret. Same secret used in scripts/make-license.py for serial generation.
// SECURITY NOTE: this is NOT cryptographically secure against motivated reverse engineers
// — anyone who decompiles app.asar can extract the secret. Adequate for casual gating.
const SECRET = '13078819ea28d426f34dd922d77228c1fe36c614968ea19d5808a35f466cd5d8';

// Crockford base32 (no I/L/O/U to reduce confusion)
const ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ';

function bytesToBase32(buf, length) {
  let bits = 0, value = 0, out = '';
  for (const b of buf) {
    value = (value << 8) | b;
    bits += 8;
    while (bits >= 5 && out.length < length) {
      out += ALPHABET[(value >>> (bits - 5)) & 0x1f];
      bits -= 5;
    }
  }
  if (bits > 0 && out.length < length) {
    out += ALPHABET[(value << (5 - bits)) & 0x1f];
  }
  return out.padEnd(length, '0').slice(0, length);
}

function _winQuery(cmd) {
  try { return execSync(cmd, { timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] }).toString(); }
  catch { return ''; }
}

function getMachineId() {
  // Source 1: C: drive volume serial via `vol C:`
  const volOut = _winQuery('cmd /c vol C:');
  const volMatch = volOut.match(/[0-9A-F]{4}-[0-9A-F]{4}/i);
  const vol = volMatch ? volMatch[0].toUpperCase() : '';

  // Source 2: motherboard UUID via wmic
  const uuidOut = _winQuery('wmic csproduct get uuid');
  const uuidMatch = uuidOut.match(/[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}/i);
  const uuid = uuidMatch ? uuidMatch[0].toUpperCase() : '';

  // Fallback: hostname + username — weaker but better than nothing
  const hostname = require('node:os').hostname();
  const username = require('node:os').userInfo().username || '';

  const fingerprint = `${vol}|${uuid}|${hostname}|${username}`;
  const hash = crypto.createHash('sha256').update(fingerprint).digest();
  return bytesToBase32(hash.subarray(0, 8), 12);
}

function _expectedBody(machineId) {
  const mac = crypto.createHmac('sha256', Buffer.from(SECRET, 'hex'));
  mac.update(machineId);
  return bytesToBase32(mac.digest().subarray(0, 10), 16);
}

function _normalizeSerial(s) {
  return String(s || '').toUpperCase().replace(/[^A-Z0-9]/g, '');
}

function _formatSerial(rawBody16) {
  // VRCT-XXXX-XXXX-XXXX-XXXX
  return 'VRCT-' + rawBody16.slice(0, 4) + '-' + rawBody16.slice(4, 8) + '-' + rawBody16.slice(8, 12) + '-' + rawBody16.slice(12, 16);
}

function validateSerial(input, machineId) {
  const flat = _normalizeSerial(input);
  if (!flat.startsWith('VRCT')) return false;
  const body = flat.slice(4);
  if (body.length !== 16) return false;
  const expected = _expectedBody(machineId || getMachineId());
  if (body.length !== expected.length) return false;
  // Constant-time comparison
  let diff = 0;
  for (let i = 0; i < body.length; i++) diff |= body.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

// ─── Persistence ────────────────────────────────────────────────────────
function _licenseFile() {
  return path.join(paths.userData(), 'license.json');
}

function loadStoredLicense() {
  try {
    const raw = fs.readFileSync(_licenseFile(), 'utf-8');
    const data = JSON.parse(raw);
    return typeof data?.serial === 'string' ? data.serial : null;
  } catch { return null; }
}

function saveLicense(serial) {
  fs.mkdirSync(paths.userData(), { recursive: true });
  fs.writeFileSync(_licenseFile(), JSON.stringify({
    serial: _formatSerial(_normalizeSerial(serial).slice(4)),
    machineId: getMachineId(),
    activatedAt: new Date().toISOString(),
  }, null, 2), 'utf-8');
}

function isLicensed() {
  const stored = loadStoredLicense();
  if (!stored) return false;
  return validateSerial(stored, getMachineId());
}

module.exports = {
  getMachineId, validateSerial, loadStoredLicense, saveLicense, isLicensed,
};
