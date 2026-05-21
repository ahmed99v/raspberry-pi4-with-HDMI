"""
LICENSE GENERATOR - Vendor-side tool (DO NOT SHIP TO CUSTOMERS)
Run on YOUR development machine to issue signed license files.

First-time setup (run once, ever):
    python3 generate_license.py keygen
    # Copy the printed public key into license_manager.py
    # Back up vendor_private.key somewhere safe and offline.

Issue a license for a customer:
    python3 generate_license.py issue \
        --hardware-id 10000000abcd1234 \
        --customer "Acme Corp" \
        --days 365

The customer's hardware ID comes from running on their Pi:
    python3 license_manager.py
or:
    cat /sys/firmware/devicetree/base/serial-number
"""

import argparse
import json
import os
import stat
import sys
import time
from datetime import datetime
from pathlib import Path

PRIVATE_KEY_PATH = "vendor_private.key"


def _lock_permissions(path):
    """Best-effort 0600 on the private key file."""
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass


def keygen():
    from nacl.signing import SigningKey
    from nacl.encoding import HexEncoder

    priv_path = Path(PRIVATE_KEY_PATH)
    if priv_path.exists():
        print(f"ERROR: {PRIVATE_KEY_PATH} already exists.")
        print("Refusing to overwrite. Delete it manually if you really want to regenerate.")
        print("(Regenerating invalidates every license you've ever issued.)")
        sys.exit(1)

    sk = SigningKey.generate()
    priv_hex = sk.encode(encoder=HexEncoder).decode()
    pub_hex = sk.verify_key.encode(encoder=HexEncoder).decode()

    priv_path.write_text(priv_hex)
    _lock_permissions(priv_path)

    print("=" * 60)
    print("Keypair generated.")
    print("=" * 60)
    print(f"Private key:  {PRIVATE_KEY_PATH}  (KEEP SECRET, BACK UP OFFLINE)")
    print()
    print("Paste this into license_manager.py:")
    print()
    print(f'    VENDOR_PUBLIC_KEY_HEX = "{pub_hex}"')
    print()
    print("Anyone with the private key can forge licenses. Treat it like a")
    print("code-signing key: offline backup, never commit to git.")
    print("=" * 60)


def issue(hardware_id, customer, days):
    from nacl.signing import SigningKey
    from nacl.encoding import HexEncoder

    priv_path = Path(PRIVATE_KEY_PATH)
    if not priv_path.exists():
        print(f"ERROR: {PRIVATE_KEY_PATH} not found. Run 'keygen' first.")
        sys.exit(1)

    sk = SigningKey(priv_path.read_text().strip().encode(), encoder=HexEncoder)

    now = int(time.time())
    payload = {
        "customer": customer,
        "hardware_id": hardware_id.lower(),
        "issued": now,
        "expiry": now + days * 86400 if days > 0 else None,
    }
    payload_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    signature_hex = sk.sign(payload_str.encode("utf-8")).signature.hex()

    license_blob = {"payload": payload_str, "signature": signature_hex}

    safe_customer = "".join(c if c.isalnum() else "_" for c in customer)
    out_path = Path(f"license_{safe_customer}.json")
    out_path.write_text(json.dumps(license_blob, indent=2))

    expiry_str = (
        datetime.fromtimestamp(payload["expiry"]).strftime("%Y-%m-%d")
        if payload["expiry"] else "never (perpetual)"
    )

    print("=" * 60)
    print("License issued.")
    print("=" * 60)
    print(f"  Customer:    {customer}")
    print(f"  Hardware ID: {hardware_id}")
    print(f"  Expires:     {expiry_str}")
    print(f"  Output:      {out_path}")
    print()
    print("Deploy on the customer's Pi:")
    print(f"  sudo mkdir -p /etc/premio")
    print(f"  sudo cp {out_path.name} /etc/premio/license.json")
    print(f"  sudo chmod 644 /etc/premio/license.json")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="License generator (vendor tool)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("keygen", help="Generate a new vendor keypair (run once)")

    issue_p = sub.add_parser("issue", help="Issue a license for a customer")
    issue_p.add_argument(
        "--hardware-id", required=True,
        help="Pi serial (from /sys/firmware/devicetree/base/serial-number)"
    )
    issue_p.add_argument("--customer", required=True, help="Customer name")
    issue_p.add_argument(
        "--days", type=int, default=365,
        help="Validity in days; 0 = perpetual (default: 365)"
    )

    args = parser.parse_args()

    if args.cmd == "keygen":
        keygen()
    elif args.cmd == "issue":
        issue(args.hardware_id, args.customer, args.days)


if __name__ == "__main__":
    main()
