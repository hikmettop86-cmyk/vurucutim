"""Generate VurucuTim license serials for given machine IDs.

Usage:
  python electron/scripts/make-license.py --machine-id ABC1DEF2GH34
  python electron/scripts/make-license.py --batch machines.txt
"""
import argparse, hashlib, hmac, sys

# MUST stay in sync with electron/src/license.js SECRET
SECRET_HEX = '13078819ea28d426f34dd922d77228c1fe36c614968ea19d5808a35f466cd5d8'
ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'   # Crockford-style


def bytes_to_base32(data: bytes, length: int) -> str:
    bits = 0
    value = 0
    out = []
    for b in data:
        value = (value << 8) | b
        bits += 8
        while bits >= 5 and len(out) < length:
            out.append(ALPHABET[(value >> (bits - 5)) & 0x1F])
            bits -= 5
    if bits > 0 and len(out) < length:
        out.append(ALPHABET[(value << (5 - bits)) & 0x1F])
    s = ''.join(out)
    return s.ljust(length, '0')[:length]


def make_serial(machine_id: str) -> str:
    machine_id = machine_id.strip().upper()
    if len(machine_id) != 12:
        raise ValueError(f"Machine ID must be 12 chars (got {len(machine_id)}: {machine_id!r})")
    secret = bytes.fromhex(SECRET_HEX)
    digest = hmac.new(secret, machine_id.encode('ascii'), hashlib.sha256).digest()
    body = bytes_to_base32(digest[:10], 16)
    return f"VRCT-{body[0:4]}-{body[4:8]}-{body[8:12]}-{body[12:16]}"


def main():
    ap = argparse.ArgumentParser(description="Generate VurucuTim license serial(s).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--machine-id", help="12-character machine ID (from app About screen)")
    g.add_argument("--batch", help="Path to text file with one machine-id per line")
    args = ap.parse_args()

    if args.machine_id:
        try:
            print(make_serial(args.machine_id))
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr); sys.exit(2)
    else:
        with open(args.batch, encoding='utf-8') as f:
            for line in f:
                mid = line.strip()
                if not mid or mid.startswith('#'):
                    continue
                try:
                    print(f"{mid}\t{make_serial(mid)}")
                except ValueError as e:
                    print(f"{mid}\tERROR: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
