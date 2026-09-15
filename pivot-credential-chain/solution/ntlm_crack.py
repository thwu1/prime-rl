#!/usr/bin/env python3
"""

Crack an NTLM hash by brute-forcing against a wordlist.
NTLM = MD4(UTF-16LE(password))
"""
import sys
from Crypto.Hash import MD4


def ntlm_hash(password: str) -> str:
    """Compute the NTLM hash (MD4 of UTF-16LE encoded password)."""
    h = MD4.new()
    h.update(password.encode("utf-16-le"))
    return h.hexdigest()


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <target_hash> <wordlist> [output_file]",
              file=sys.stderr)
        sys.exit(1)

    target = sys.argv[1].lower().strip()
    wordlist_path = sys.argv[2]
    output_path = sys.argv[3] if len(sys.argv) > 3 else None

    with open(wordlist_path, "r", errors="ignore") as wl:
        for line in wl:
            candidate = line.rstrip("\n\r")
            if not candidate:
                continue
            if ntlm_hash(candidate) == target:
                print(f"[+] Cracked: {candidate}")
                if output_path:
                    with open(output_path, "w") as f:
                        f.write(candidate)
                sys.exit(0)

    print("[-] No match found", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
