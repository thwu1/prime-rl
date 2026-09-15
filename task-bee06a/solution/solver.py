#!/usr/bin/env python3
"""
DNS tunnel forensics solver.
Recovers exfiltrated data, evaluates attacker OPSEC, and builds a detection engine.
"""

import subprocess
import hashlib
import base64
import os
import re
from collections import Counter


def run(cmd):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


def extract_dns_queries_tshark(pcap_path):
    """Use tshark to extract DNS query names from the PCAP."""
    out = run(
        f'tshark -r {pcap_path} -T fields -e dns.qry.name '
        f'-Y "dns.flags.response == 0" 2>/dev/null'
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def analyze_binary(binary_path):
    """Use strings and objdump to understand the tunnel client."""
    strings_out = run(f'strings {binary_path}')
    print("[*] strings output from binary (excerpt):")
    for line in strings_out.splitlines():
        if any(kw in line for kw in ['B32', '234567', '%s.%', 'sha256',
                                      'SHA256', 'EVP_', 'domain', 'usage']):
            print(f"    {line}")

    # Look for format string to understand subdomain pattern
    fmt_match = re.search(r'%s\.%02x\.(\w+)\.%s', strings_out)
    if fmt_match:
        marker = fmt_match.group(1)
        print(f"[*] Detected subdomain marker label: '{marker}'")
    else:
        marker = 'x'

    # Look for base32 alphabet
    has_b32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567' in strings_out
    print(f"[*] Base32 alphabet detected: {has_b32}")

    return marker


def decrypt_notes(notes_path):
    """Use openssl to decrypt the encrypted notes file."""
    history_path = '/app/evidence/workstation/.bash_history'
    with open(history_path) as f:
        history = f.read()

    match = re.search(r'-pass pass:(\S+)', history)
    if not match:
        print("[!] Could not find passphrase in bash history")
        return ""
    passphrase = match.group(1)
    print(f"[*] Found passphrase in bash_history: {passphrase}")

    plaintext = run(
        f'openssl enc -aes-256-cbc -pbkdf2 -d -in {notes_path} '
        f'-pass pass:{passphrase} 2>/dev/null'
    )
    print(f"[*] Decrypted notes:\n{plaintext}")
    return plaintext


def identify_tunnel_domain(queries, marker='x'):
    """Analyze DNS queries to identify the tunnel base domain."""
    candidate_bases = Counter()

    for domain in queries:
        labels = domain.split('.')
        if len(labels) < 5:
            continue
        for i in range(2, len(labels) - 2):
            if labels[i] == marker and len(labels[i]) <= 2:
                first = labels[i - 2]
                second = labels[i - 1]
                base = '.'.join(labels[i + 1:])
                if (len(first) >= 10 and
                        all(c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567' for c in first) and
                        len(second) == 2 and
                        all(c in '0123456789abcdef' for c in second)):
                    candidate_bases[base] += 1

    if not candidate_bases:
        return None

    tunnel_domain = candidate_bases.most_common(1)[0][0]
    return tunnel_domain


def extract_tunnel_chunks(queries, tunnel_domain, marker='x'):
    """Extract encoded chunks from tunnel queries."""
    chunks = {}
    td_labels = tunnel_domain.split('.')
    td_len = len(td_labels)

    for domain in queries:
        if not domain.endswith(f"{marker}.{tunnel_domain}"):
            continue
        labels = domain.split('.')
        marker_idx = len(labels) - td_len - 1
        if marker_idx >= 2 and labels[marker_idx] == marker:
            seq_hex = labels[marker_idx - 1]
            chunk = labels[marker_idx - 2]
            try:
                seq = int(seq_hex, 16)
                chunks[seq] = chunk
            except ValueError:
                continue

    return chunks


def xor_decrypt(data, key):
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])


def write_assessment(output_dir):
    """Write the OPSEC assessment based on forensic findings."""
    assessment = """OPERATIONAL SECURITY ASSESSMENT -- DNS EXFILTRATION INCIDENT

1. CREDENTIAL EXPOSURE VIA SHELL HISTORY
The attacker's encryption passphrase was stored in plaintext in .bash_history. The openssl
command with the -pass pass: argument is fully visible, allowing trivial decryption of the
operational notes file. The bash_history shows the attacker attempted "history -c" but this
was recorded before execution, preserving the evidence. Proper tradecraft requires passphrase
entry via stdin or ephemeral environment variables, combined with HISTFILE=/dev/null before
any sensitive commands.

2. WEAK ENCRYPTION -- XOR CIPHER
The exfiltration tool uses a simple XOR cipher rather than a robust authenticated encryption
algorithm like AES-GCM or ChaCha20-Poly1305. XOR encryption is trivially reversible with
known-plaintext attacks. Since the exfiltrated data is structured JSON with predictable byte
positions (opening brace, quote characters, common key names), an analyst can recover key
bytes without any external information. The lack of authentication also means modified
ciphertext cannot be detected.

3. KEY DERIVATION FROM OBSERVABLE DOMAIN
The encryption key is derived via SHA256 of the tunnel domain name, truncated to 16 bytes.
The tunnel domain is directly observable in DNS traffic -- it appears in every exfiltration
query. Once an analyst identifies the tunnel base domain through traffic analysis, the
encryption key is fully determined with zero cryptanalytic effort. A secure design would use
a pre-shared key or asymmetric key exchange independent of the transport channel.

4. INCOMPLETE ARTIFACT CLEANUP
Despite shred commands appearing in the command history, the exfiltool binary remained on
disk at the workstation. This forensic artifact enabled complete reverse engineering of the
encoding scheme (base32), encryption algorithm (XOR), key derivation method (SHA256 of domain),
and subdomain format string. The binary was stripped but not obfuscated, making static analysis
straightforward with strings and objdump. A competent operator would remove or overwrite the
binary and verify deletion.

5. DETERMINISTIC AND SEQUENTIAL TRAFFIC PATTERNS
Tunnel queries use incrementing hex sequence numbers (00, 01, 02, ...) in the second subdomain
label, making automated detection and data reassembly trivially simple. The consistent
single-character marker label, fixed-length base32-encoded chunks, and predictable label
structure create a signature that is easily distinguishable from legitimate DNS traffic through
basic structural heuristics. Adding randomized padding, variable chunk sizes, timing jitter,
and non-sequential identifiers would significantly complicate detection."""

    with open(os.path.join(output_dir, 'assessment.txt'), 'w') as f:
        f.write(assessment.strip())
    print("[*] Assessment written to assessment.txt")


def write_detector(output_dir):
    """Write the DNS tunnel detection engine."""
    detector_code = '''"""
DNS tunnel query detector.
Identifies DNS queries that exhibit structural patterns consistent with
data exfiltration via subdomain encoding.
"""

B32_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def detect(query: str) -> bool:
    """Detect DNS tunnel queries based on structural subdomain patterns.

    Returns True if the query matches the signature of DNS data exfiltration:
    a long base32-encoded subdomain label followed by a hex sequence counter
    and a short marker label.

    Args:
        query: DNS query name (e.g. "MFZWI.03.x.tunnel.example.com")

    Returns:
        True if suspected tunnel query, False otherwise.
    """
    labels = query.rstrip(".").split(".")
    if len(labels) < 4:
        return False

    first = labels[0]

    # Encoded data label must be substantial length
    if len(first) < 10:
        return False

    # Check for base32 character set (uppercase A-Z plus digits 2-7)
    if not all(c in B32_CHARS for c in first):
        return False

    # Second label should be a 2-character hex sequence number
    second = labels[1]
    if len(second) != 2:
        return False
    try:
        int(second, 16)
    except ValueError:
        return False

    # Third label should be a short marker (1-2 chars)
    if len(labels[2]) > 2:
        return False

    return True
'''

    with open(os.path.join(output_dir, 'detector.py'), 'w') as f:
        f.write(detector_code.strip() + '\n')
    print("[*] Detector written to detector.py")


def main():
    pcap_path = '/app/evidence/traffic.pcap'
    binary_path = '/app/evidence/workstation/exfiltool'
    notes_path = '/app/evidence/workstation/.config/notes.enc'
    output_dir = '/app/results'
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Reverse-engineer the binary to understand the encoding scheme
    print("[*] Analyzing binary artifact...")
    marker = analyze_binary(binary_path)

    # Step 2: Decrypt operational notes for context
    print("\n[*] Decrypting operational notes...")
    decrypt_notes(notes_path)

    # Step 3: Extract DNS queries from PCAP using tshark
    print("\n[*] Extracting DNS queries from PCAP with tshark...")
    queries = extract_dns_queries_tshark(pcap_path)
    print(f"[*] Total DNS queries extracted: {len(queries)}")

    # Step 4: Identify tunnel domain from traffic patterns
    print("\n[*] Identifying tunnel domain...")
    tunnel_domain = identify_tunnel_domain(queries, marker)
    print(f"[*] Tunnel domain: {tunnel_domain}")

    # Step 5: Extract data chunks from tunnel queries
    print("\n[*] Extracting tunnel data chunks...")
    chunks = extract_tunnel_chunks(queries, tunnel_domain, marker)
    print(f"[*] Found {len(chunks)} tunnel packets")

    # Step 6: Reassemble, decode, and decrypt
    max_seq = max(chunks.keys())
    ordered = []
    for i in range(max_seq + 1):
        if i in chunks:
            ordered.append(chunks[i])
        else:
            print(f"[!] Missing sequence {i}")
    encoded = ''.join(ordered)

    # Base32 decode (add padding)
    padded = encoded + '=' * (-len(encoded) % 8)
    encrypted = base64.b32decode(padded)

    # XOR decrypt with SHA256(tunnel_domain)[:16]
    key = hashlib.sha256(tunnel_domain.encode()).digest()[:16]
    plaintext = xor_decrypt(encrypted, key)
    plaintext_str = plaintext.decode('utf-8')

    # Step 7: Write recovery results
    with open(os.path.join(output_dir, 'tunnel_domain.txt'), 'w') as f:
        f.write(tunnel_domain)

    with open(os.path.join(output_dir, 'packet_count.txt'), 'w') as f:
        f.write(str(len(chunks)))

    with open(os.path.join(output_dir, 'exfiltrated.txt'), 'w') as f:
        f.write(plaintext_str)

    checksum = hashlib.sha256(plaintext_str.encode('utf-8')).hexdigest()
    with open(os.path.join(output_dir, 'checksum.txt'), 'w') as f:
        f.write(checksum)

    print(f"\n[*] Plaintext: {plaintext_str[:80]}...")
    print(f"[*] SHA256: {checksum}")

    # Step 8: Write OPSEC assessment (evaluate)
    print("\n[*] Writing security assessment...")
    write_assessment(output_dir)

    # Step 9: Write detection engine (create)
    print("\n[*] Writing detection engine...")
    write_detector(output_dir)

    print("\n[*] All results written to /app/results/")


if __name__ == '__main__':
    main()
