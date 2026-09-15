#!/usr/bin/env python3
"""
Extract hidden payload from multi-stage obfuscated build system files,
produce a forensic triage report, and create a heuristic detection script.

Reverses the three-stage obfuscation pipeline:
  Stage 0: tr byte-swap cipher on corrupted xz stream -> Stage 1 script
  Stage 1: head-chain data interleaving + tr substitution cipher
  Stage 2: AWK RC4 variant decryption + xz -> payload

Then creates a reusable detection script that uses structural/behavioral
heuristics to identify supply-chain backdoor patterns in autotools projects.
"""
import hashlib
import json
import lzma
import os
import re
import sys


def apply_swap(data, swap_map):
    """Apply byte-level swap (self-inverse)."""
    return bytes(swap_map.get(b, b) for b in data)


def parse_tr_ranges(s):
    """Parse a tr-style octal range string into a flat list of byte values.

    Handles: \\NNN (1-3 octal digits), literal chars, and ranges (X-Y).
    Example: '\\5-\\51\\204-\\377' -> [5,6,...,41,132,...,255]
    """
    result = []
    i = 0
    while i < len(s):
        # Parse one value
        if s[i] == '\\':
            i += 1
            oct_str = ""
            while i < len(s) and s[i] in '0123456789' and len(oct_str) < 3:
                oct_str += s[i]
                i += 1
            val = int(oct_str, 8)
        else:
            val = ord(s[i])
            i += 1

        result.append(val)

        # Check for range
        if i < len(s) and s[i] == '-':
            i += 1  # skip '-'
            if i < len(s):
                if s[i] == '\\':
                    i += 1
                    oct_str = ""
                    while i < len(s) and s[i] in '0123456789' and len(oct_str) < 3:
                        oct_str += s[i]
                        i += 1
                    end_val = int(oct_str, 8)
                else:
                    end_val = ord(s[i])
                    i += 1
                for v in range(result[-1] + 1, end_val + 1):
                    result.append(v)

    return result


def make_decrypt_table(from_values):
    """Build decryption table for tr "FROM" "\\0-\\377".

    tr maps FROM[i] -> i, so decrypt_table[FROM[i]] = i.
    """
    table = [0] * 256
    for i, v in enumerate(from_values):
        table[v] = i
    return bytes(table)


def apply_table(data, table):
    return bytes(table[b] for b in data)


def extract_head_params(head_chain_str):
    """Parse head chain to extract (skip_sizes, read_sizes)."""
    sizes = [int(m) for m in re.findall(r'head -c \+(\d+)', head_chain_str)]
    skip_sizes = sizes[0::2]  # even indices: skip (>/dev/null)
    read_sizes = sizes[1::2]  # odd indices: read
    return skip_sizes, read_sizes


def apply_head_chain(data, skip_sizes, read_sizes):
    """Apply head chain: alternately skip and read blocks."""
    result = bytearray()
    offset = 0
    for i in range(len(read_sizes)):
        offset += skip_sizes[i]
        take = read_sizes[i]
        result.extend(data[offset:offset + take])
        offset += take
    return bytes(result)


def rc4_decrypt(data, k_mult, k_add, skip):
    """Decrypt with modified RC4: plaintext = (ciphertext + keystream) % 256.

    Key schedule: c[i] = (i * k_mult + k_add) % 256
    Drops first `skip` PRNG outputs before decrypting.
    Uses addition mod 256 instead of XOR (AWK lacks bitwise ops).
    """
    m = 256
    c = [(i * k_mult + k_add) % m for i in range(m)]
    i = j = 0
    for _ in range(skip):
        i = (i + 1) % m
        a = c[i]
        j = (j + a) % m
        c[i], c[j] = c[j], c[i]
    result = bytearray()
    for byte in data:
        i = (i + 1) % m
        a = c[i]
        j = (j + a) % m
        b = c[j]
        c[i], c[j] = c[j], c[i]
        k = c[(a + b) % m]
        result.append((byte + k) % m)
    return bytes(result)


def create_detection_script():
    """Create the heuristic detection script at /app/detect.py."""
    script = r'''#!/usr/bin/env python3
"""
Heuristic detection tool for supply-chain backdoor patterns in autotools projects.

Detects:
1. Build-system code injection: M4/configure files with grep-to-eval pipelines
   that reference data directories (indicator of embedded payload extraction).
2. Suspicious data files: compressed/binary files in directories targeted by
   build-system injection vectors (potential payload containers).
3. Suspicious-but-benign patterns: scripts/macros using eval+transform tools
   in contexts that don't involve data-directory scanning.

Usage: python3 detect.py <project_dir>
Output: JSON to stdout with alert list.
"""
import json
import os
import re
import sys


COMPRESSED_EXTENSIONS = {'.xz', '.lzma', '.gz', '.bz2', '.zst', '.tar',
                         '.zip', '.7z', '.lz', '.lzo'}


def scan_for_build_injection(project_dir):
    """Scan M4 macros and configure scripts for grep-to-eval pipelines."""
    injection_files = []
    target_dirs = set()

    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames.sort()
        for fname in sorted(filenames):
            if not fname.endswith(('.m4', '.ac', '.am', '.in')) and \
               fname not in ('configure', 'config.status'):
                continue

            fpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fpath, project_dir)

            try:
                with open(fpath) as f:
                    content = f.read()
            except (UnicodeDecodeError, PermissionError):
                continue

            # Pattern: grep searching data files + piping to eval/shell/xz
            # This is the hallmark of xz-style supply chain backdoors:
            # the build system greps for markers in data files and executes
            # what it finds through a deobfuscation pipeline.
            grep_eval = re.search(
                r'grep\b.*\|.*(?:eval|xz|/bin/sh|bash)',
                content, re.DOTALL
            )
            grep_to_config = re.search(
                r'grep\b[^|]*\$(?:srcdir|top_srcdir)[^|]*\|',
                content
            )
            eval_config = re.search(
                r'eval\s+\$\S*config',
                content
            )

            if grep_eval or (grep_to_config and eval_config):
                injection_files.append(relpath)
                # Extract target directories from grep commands
                dir_matches = re.findall(
                    r'grep[^|]*\$(?:srcdir|top_srcdir)/([^\s"\'|]+)',
                    content
                )
                for dm in dir_matches:
                    # Normalize: strip trailing filename patterns
                    d = dm.rstrip('/')
                    if '/' in d:
                        target_dirs.add(d)
                    else:
                        target_dirs.add(d)
                # Also try absolute-style paths
                dir_matches2 = re.findall(
                    r'grep[^|]*\s+(\S*(?:tests|data|files)[^\s"\'|]*)',
                    content
                )
                for dm in dir_matches2:
                    d = dm.strip().rstrip('/')
                    if d.startswith('$'):
                        d = re.sub(r'^\$\w+/', '', d)
                    if d:
                        target_dirs.add(d)

    return injection_files, target_dirs


def scan_target_dirs(project_dir, target_dirs):
    """Flag compressed/binary files in directories targeted by injection vectors."""
    flagged = []
    for td in target_dirs:
        target_path = os.path.join(project_dir, td)
        if not os.path.isdir(target_path):
            # td might be a path with glob/file suffix; try parent
            parent = os.path.dirname(td)
            target_path = os.path.join(project_dir, parent)
            if not os.path.isdir(target_path):
                continue
            td = parent

        for fname in sorted(os.listdir(target_path)):
            fpath = os.path.join(target_path, fname)
            if not os.path.isfile(fpath):
                continue
            relpath = os.path.relpath(fpath, project_dir)
            _, ext = os.path.splitext(fname)

            # Flag compressed archives and binary files in target dirs
            if ext.lower() in COMPRESSED_EXTENSIONS:
                flagged.append(relpath)
                continue

            # Check for binary content (non-text)
            try:
                with open(fpath, 'rb') as f:
                    sample = f.read(4096)
                if b'\x00' in sample:
                    flagged.append(relpath)
                    continue
                # Check for embedded script markers in binary-like data
                if b'####' in sample and ext not in ('.sh', '.py', '.m4'):
                    flagged.append(relpath)
            except PermissionError:
                pass

    return flagged


def scan_suspicious_benign(project_dir, already_flagged):
    """Find files that look suspicious but likely aren't malicious."""
    flagged_set = set(already_flagged)
    suspicious = []

    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fpath, project_dir)

            if relpath in flagged_set:
                continue
            if not os.path.isfile(fpath):
                continue

            try:
                with open(fpath, 'rb') as f:
                    raw = f.read()
            except PermissionError:
                continue

            is_suspicious = False
            reason = ""

            # Check for high-entropy binary data in non-standard locations
            sample = raw[:8192]
            if b'\x00' in sample and not fname.endswith(('.o', '.so', '.a')):
                non_text = sum(1 for b in sample if b > 127 or b == 0)
                if non_text > len(sample) * 0.3:
                    is_suspicious = True
                    reason = "High-entropy binary data in non-compiled file"

            # Check for text-based suspicious patterns
            if not is_suspicious:
                try:
                    text = raw.decode('utf-8', errors='strict')
                except UnicodeDecodeError:
                    is_suspicious = True
                    reason = "Binary file with non-standard extension"
                else:
                    has_eval = 'eval' in text
                    has_transform = bool(re.search(
                        r'\b(?:tr|awk|sed)\s', text
                    ))
                    has_m4_macro = 'AC_DEFUN' in text

                    if has_eval and has_transform:
                        is_suspicious = True
                        reason = "Script combines eval with data transformation tools"
                    elif has_m4_macro and has_eval:
                        is_suspicious = True
                        reason = "M4 macro uses eval for dynamic configuration"

            if is_suspicious:
                suspicious.append((relpath, reason))

    return suspicious


def main():
    if len(sys.argv) < 2:
        print("Usage: detect.py <project_dir>", file=sys.stderr)
        sys.exit(1)

    project_dir = sys.argv[1]
    if not os.path.isdir(project_dir):
        print(f"Error: {project_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    alerts = []

    # Phase 1: Find build-system injection vectors
    injection_files, target_dirs = scan_for_build_injection(project_dir)
    for f in injection_files:
        alerts.append({
            "file": f,
            "risk": "high",
            "indicator": ("Build-system file contains grep-to-eval pipeline "
                          "targeting data directories — potential code injection vector")
        })

    # Phase 2: Flag data files in targeted directories
    high_files = set(injection_files)
    data_files = scan_target_dirs(project_dir, target_dirs)
    for f in data_files:
        if f not in high_files:
            alerts.append({
                "file": f,
                "risk": "high",
                "indicator": ("Compressed/binary file in directory scanned by "
                              "build-system injection vector — potential payload container")
            })
            high_files.add(f)

    # Phase 3: Find suspicious-but-benign patterns
    suspicious = scan_suspicious_benign(project_dir, high_files)
    for f, reason in suspicious:
        alerts.append({
            "file": f,
            "risk": "medium",
            "indicator": reason
        })

    output = {"alerts": alerts}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
'''
    with open("/app/detect.py", "w") as f:
        f.write(script)
    os.chmod("/app/detect.py", 0o755)


def main():
    project = "/app/project"

    # Track which files we read as part of the backdoor chain
    backdoor_files_consumed = []

    # ===== STAGE 0: Analyze build-to-host.m4 =====
    # The M4 macro applies: tr "\t \-_" " \t_\-" | xz -d
    # This is a 4-byte self-inverse swap: tab<->space, dash<->underscore
    swap_map = {0x09: 0x20, 0x20: 0x09, 0x2D: 0x5F, 0x5F: 0x2D}

    entry_point = "m4/build-to-host.m4"
    backdoor_files_consumed.append(entry_point)

    with open(os.path.join(project, "tests/files/bad-stream.xz"), "rb") as f:
        bad_stream = f.read()
    backdoor_files_consumed.append("tests/files/bad-stream.xz")

    # Strip trailing ####World#### marker (used for grep-based file discovery)
    marker = bad_stream.find(b"####World####")
    xz_corrupted = bad_stream[:marker] if marker > 0 else bad_stream

    # Reverse the byte swap to restore valid xz data
    xz_fixed = apply_swap(xz_corrupted, swap_map)

    # Decompress to get Stage 1 script
    stage1 = lzma.decompress(xz_fixed, format=lzma.FORMAT_XZ).decode()

    # ===== STAGE 1: Extract Stage 2 from good-archive.lzma =====
    # Parse head chain: export i="(head chain here)"
    head_match = re.search(r'export i="\((.+?)\)"', stage1)
    head_chain = head_match.group(1)
    skip_sizes, read_sizes = extract_head_params(head_chain)

    # Parse tail offset
    tail_offset = int(re.search(r'tail -c \+(\d+)', stage1).group(1))

    # Parse tr cipher key
    tr_from_str = re.search(r'tr "([^"]+)" "\\0-\\377"', stage1).group(1)
    from_values = parse_tr_ranges(tr_from_str)
    decrypt_table = make_decrypt_table(from_values)

    # Decompress the archive and apply head chain
    with open(os.path.join(project, "tests/files/good-archive.lzma"), "rb") as f:
        archive = f.read()
    backdoor_files_consumed.append("tests/files/good-archive.lzma")

    decompressed = lzma.decompress(archive, format=lzma.FORMAT_ALONE)
    extracted = apply_head_chain(decompressed, skip_sizes, read_sizes)

    # Get Stage 2 ciphered portion (after tail offset)
    stage2_ciphered = extracted[tail_offset - 1:]  # tail -c +N is 1-indexed

    # Apply tr decryption and decompress
    stage2_xz = apply_table(stage2_ciphered, decrypt_table)
    stage2 = lzma.decompress(stage2_xz, format=lzma.FORMAT_XZ).decode()

    # ===== STAGE 2: RC4-decrypt payload from good-archive.lzma =====
    # Parse RC4 parameters from AWK script
    k_mult = int(re.search(r'\(i\*(\d+)\)\+', stage2).group(1))
    k_add = int(re.search(r'\*\d+\)\+(\d+)\)', stage2).group(1))
    rc4_skip = int(re.search(r'for\(l=0;l<(\d+);l\+\+\)', stage2).group(1))
    payload_size = int(re.search(r'^W=(\d+)', stage2, re.MULTILINE).group(1))

    # RC4 ciphertext is the portion before the tail offset
    rc4_ciphertext = extracted[:tail_offset - 1]

    # Decrypt and decompress
    decrypted_xz = rc4_decrypt(rc4_ciphertext, k_mult, k_add, rc4_skip)
    payload = lzma.decompress(decrypted_xz, format=lzma.FORMAT_XZ)

    assert len(payload) == payload_size

    # Write extraction results
    payload_hash = hashlib.sha256(payload).hexdigest()

    with open("/app/payload.bin", "wb") as f:
        f.write(payload)

    with open("/app/answer.txt", "w") as f:
        f.write(payload_hash)

    # ===== FORENSIC REPORT =====
    # Classify remaining project files as benign-suspicious or clean.
    backdoor_set = set(backdoor_files_consumed)
    benign_suspicious = []

    for dirpath, dirnames, filenames in os.walk(project):
        dirnames.sort()
        for fname in sorted(filenames):
            fpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fpath, project)

            # Skip known backdoor files
            if relpath in backdoor_set:
                continue

            # Skip non-regular files
            if not os.path.isfile(fpath):
                continue

            # Read file content in binary mode
            with open(fpath, "rb") as fh:
                raw = fh.read()

            suspicious = False

            # Check 1: binary content indicators
            sample = raw[:8192]
            if b'\x00' in sample:
                suspicious = True
            elif len(sample) > 100:
                non_ascii_count = 0
                for byte_val in sample:
                    if byte_val > 127:
                        non_ascii_count += 1
                if non_ascii_count > len(sample) * 0.3:
                    suspicious = True

            # Check 2: text-based suspicious patterns
            if not suspicious:
                text = raw.decode("utf-8", errors="replace")

                has_eval = "eval" in text
                has_tr = "tr " in text or "tr\t" in text
                has_awk = "awk " in text or "awk\t" in text or "awk'" in text
                has_sed = "sed " in text or "sed\t" in text
                has_transform = has_tr or has_awk or has_sed

                # Shell scripts with eval + data transformation tools
                if has_eval and has_transform:
                    suspicious = True

                # M4 autoconf macros using eval
                if not suspicious and "AC_DEFUN" in text and has_eval:
                    suspicious = True

                # Scripts that generate or reference hash/entropy data
                if not suspicious:
                    has_hash_ref = ("hashlib" in text or "sha256" in text
                                    or "entropy" in text)
                    has_data_ref = ".dat" in text or "corpus" in text
                    if has_hash_ref and has_data_ref:
                        suspicious = True

            if suspicious:
                benign_suspicious.append(relpath)
                sys.stderr.write(
                    f"[classify] suspicious: {relpath}\n"
                )

    report = {
        "backdoor_entry_point": entry_point,
        "backdoor_files": backdoor_files_consumed,
        "benign_suspicious_files": sorted(benign_suspicious),
    }
    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    # ===== DETECTION SCRIPT =====
    create_detection_script()

    sys.stderr.write(
        f"[extract] Done. Payload hash: {payload_hash}\n"
        f"[extract] Benign suspicious: {sorted(benign_suspicious)}\n"
        f"[extract] Detection script created at /app/detect.py\n"
    )


if __name__ == "__main__":
    main()
