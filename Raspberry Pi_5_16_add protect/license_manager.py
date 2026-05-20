"""
LICENSE MANAGER - Anti-piracy protection
Hardware-bound, Ed25519-signed license verification.

Verifies on startup and re-verifies hourly (catches mid-session expiry).
On any failure the process aborts with sys.exit(1).
"""

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# ============================================================
# VENDOR PUBLIC KEY (Ed25519, hex-encoded, 64 chars)
# Generated once by generate_license.py and pasted here.
# The matching PRIVATE key stays on the vendor's machine only.
# ============================================================
VENDOR_PUBLIC_KEY_HEX = "0000000000000000000000000000000000000000000000000000000000000000"

# License file location on the deployed Pi
LICENSE_FILE_PATH = "/etc/premio/license.json"

# Re-check cadence - hourly catches expiry without burning CPU
RECHECK_INTERVAL_SEC = 3600


def get_hardware_id():
    """Read the Pi's unique CPU serial. Returns lowercase hex string or None."""
    try:
        with open("/sys/firmware/devicetree/base/serial-number", "rb") as f:
            raw = f.read().rstrip(b"\x00").decode("ascii", errors="ignore").strip()
            if raw:
                return raw.lower()
    except (FileNotFoundError, PermissionError):
        pass

    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    serial = line.split(":", 1)[1].strip()
                    if serial:
                        return serial.lower()
    except (FileNotFoundError, PermissionError):
        pass

    return None


def _fail(reason):
    """License failures are fatal - print and abort."""
    print("=" * 60)
    print("LICENSE VERIFICATION FAILED")
    print(f"  Reason: {reason}")
    print("  Contact your vendor for a valid license.")
    print("=" * 60)
    sys.exit(1)


def _verify_once():
    """Single verification pass. Returns parsed payload on success."""
    try:
        from nacl.signing import VerifyKey
        from nacl.encoding import HexEncoder
        from nacl.exceptions import BadSignatureError
    except ImportError:
        _fail("pynacl is not installed (run: sudo pip3 install pynacl)")

    license_path = Path(LICENSE_FILE_PATH)
    if not license_path.exists():
        _fail(f"license file not found at {LICENSE_FILE_PATH}")

    try:
        license_data = json.loads(license_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        _fail(f"license file is unreadable or corrupt ({e})")

    payload_str = license_data.get("payload")
    signature_hex = license_data.get("signature")
    if not payload_str or not signature_hex:
        _fail("license file is malformed (missing payload or signature)")

    try:
        verify_key = VerifyKey(VENDOR_PUBLIC_KEY_HEX, encoder=HexEncoder)
        verify_key.verify(payload_str.encode("utf-8"), bytes.fromhex(signature_hex))
    except BadSignatureError:
        _fail("license signature is invalid (tampered or wrong vendor)")
    except Exception as e:
        _fail(f"signature verification error ({e})")

    try:
        payload = json.loads(payload_str)
    except json.JSONDecodeError:
        _fail("license payload is malformed")

    expected_hw = payload.get("hardware_id", "").lower()
    actual_hw = get_hardware_id()
    if not actual_hw:
        _fail("cannot read hardware ID from this Pi")
    if expected_hw != actual_hw:
        _fail(
            "license is not valid for this hardware "
            f"(expected ...{expected_hw[-8:]}, got ...{actual_hw[-8:]})"
        )

    expiry = payload.get("expiry")
    if expiry is not None and time.time() > expiry:
        exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
        _fail(f"license expired on {exp_str}")

    return payload


def verify_license():
    """
    Verify license at startup, then keep re-checking in a daemon thread.
    Call this before any other initialization.
    """
    if VENDOR_PUBLIC_KEY_HEX == "0" * 64:
        _fail("vendor public key not configured in license_manager.py")

    payload = _verify_once()

    customer = payload.get("customer", "unknown")
    expiry = payload.get("expiry")
    if expiry:
        exp_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d")
        expiry_msg = f"valid until {exp_str}"
    else:
        expiry_msg = "perpetual"

    hw = get_hardware_id() or ""
    print("=" * 60)
    print("License verified")
    print(f"  Customer: {customer}")
    print(f"  Hardware: ...{hw[-12:]}")
    print(f"  Status:   {expiry_msg}")
    print("=" * 60)

    def _periodic_check():
        while True:
            time.sleep(RECHECK_INTERVAL_SEC)
            _verify_once()

    threading.Thread(target=_periodic_check, daemon=True).start()


if __name__ == "__main__":
    # Standalone diagnostic mode: print this Pi's hardware ID
    hw = get_hardware_id()
    if hw:
        print(f"This Pi's hardware ID: {hw}")
        print("Send this to your vendor to request a license.")
    else:
        print("ERROR: could not read hardware ID.")
        sys.exit(1)
