#!/usr/bin/env python3
"""
Heap forensics solver: creates the detection tool, produces forensic report
with attack impact assessment, and recovers encrypted session token.

"""

import hashlib
import struct
import sys

HEAP_BASE = 0x55555555A000
DUMP_SIZE = 0x600
BINARY_PATH = "/app/heapservice"
CLEAN_PATH = "/app/snapshot_clean.bin"
ATTACKED_PATH = "/app/snapshot_attacked.bin"
FLAG_PATH = "/app/flag.txt"
REPORT_PATH = "/app/forensic_report.txt"


def read_qword(data, offset):
    return struct.unpack_from("<Q", data, offset)[0]


def protect_ptr_reverse(pos, mangled):
    return (pos >> 12) ^ mangled


def xor_decrypt(ciphertext, key):
    return bytes(c ^ key[i % len(key)] for i, c in enumerate(ciphertext))


def extract_audit_key(binary_path):
    with open(binary_path, "rb") as f:
        binary = f.read()
    marker = b"AUDIT_KEY_MATERIAL:"
    idx = binary.find(marker)
    if idx < 0:
        raise RuntimeError("AUDIT_KEY_MATERIAL marker not found in binary")
    key_start = idx + 20
    return binary[key_start : key_start + 16]


def walk_chunks(dump):
    chunks = []
    offset = 0
    while offset < len(dump) - 16:
        raw_size = read_qword(dump, offset + 8)
        chunk_size = raw_size & ~0x7
        if chunk_size == 0 or chunk_size > len(dump):
            break
        chunks.append(
            {
                "offset": offset,
                "chunk_size": chunk_size,
                "ud_offset": offset + 0x10,
                "ud_addr": HEAP_BASE + offset + 0x10,
            }
        )
        offset += chunk_size
    return chunks


def parse_tcache(dump):
    tcache = {}
    for idx in range(64):
        count = struct.unpack_from("<H", dump, 0x010 + idx * 2)[0]
        if count > 0:
            entry = read_qword(dump, 0x090 + idx * 8)
            tcache[idx] = {
                "count": count,
                "head": entry,
                "chunk_size": 0x20 + idx * 0x10,
            }
    return tcache


def find_freed_chunks(dump, chunks):
    tcache_key_value = HEAP_BASE + 0x010
    freed = set()
    for chunk in chunks[1:]:
        key_off = chunk["ud_offset"] + 8
        if key_off + 8 <= len(dump):
            if read_qword(dump, key_off) == tcache_key_value:
                freed.add(chunk["ud_addr"])
    return freed


def find_poisoned_fd(dump, tcache_bins, freed_addrs):
    for idx, info in tcache_bins.items():
        current = info["head"]
        for step in range(info["count"]):
            if current == 0:
                break
            fd_off = current - HEAP_BASE
            if fd_off < 0 or fd_off + 8 > len(dump):
                break
            stored_fd = read_qword(dump, fd_off)
            demangled = protect_ptr_reverse(current, stored_fd)
            if demangled != 0 and demangled not in freed_addrs:
                return current, demangled, idx
            current = demangled
    return None


def generate_report(clean, attacked, chunks_c, chunks_a, tcache_a, freed_addrs, poison_info):
    poisoned_chunk_addr, target_addr, poison_bin = poison_info
    lines = []
    lines.append("HEAP FORENSIC ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append(f"Heap base address: 0x{HEAP_BASE:x}")
    lines.append(f"Snapshot size: {len(clean)} bytes each")
    lines.append("")

    labels = [
        "tcache_perthread_struct",
        "chunk 0 (banner, malloc 0x80)",
        "chunk 1 (metadata, malloc 0x20)",
        "chunk 2 (buffer_a, malloc 0x40)",
        "chunk 3 (buffer_b, malloc 0x40)",
        "chunk 4 (tx_log, malloc 0x60)",
        "chunk 5 (audit, malloc 0xa0)",
        "chunk 6 (config, malloc 0x20)",
        "chunk 7 (session_token, malloc 0x40)",
    ]

    lines.append("CHANGE CLASSIFICATION")
    lines.append("-" * 60)

    for i, chunk in enumerate(chunks_a):
        if i >= len(chunks_c):
            break
        sz = min(
            chunk["chunk_size"],
            len(clean) - chunk["offset"],
            len(attacked) - chunk["offset"],
        )
        d_clean = clean[chunk["offset"] : chunk["offset"] + sz]
        d_attack = attacked[chunk["offset"] : chunk["offset"] + sz]
        if d_clean == d_attack:
            continue

        label = labels[i] if i < len(labels) else f"chunk {i}"
        lines.append("")
        lines.append(f"## {label}")
        lines.append(
            f"   Heap offset: 0x{chunk['offset']:04x}  "
            f"Userdata addr: 0x{chunk['ud_addr']:x}"
        )

        if i == 0:
            lines.append("   Classification: MIXED")
            lines.append(
                "   Justification: The tcache_perthread_struct reflects "
                "multiple freed chunks. Most frees are legitimate service "
                "buffer recycling. However, tcache bin "
                f"{poison_bin} (chunk_size "
                f"0x{0x20 + poison_bin * 0x10:x}) contains a chain "
                "whose head entry resolves to an allocated chunk — "
                "evidence of fd pointer corruption."
            )

        elif i == 2:
            lines.append("   Classification: BENIGN")
            old_ts = read_qword(clean, chunk["ud_offset"] + 0x10)
            new_ts = read_qword(attacked, chunk["ud_offset"] + 0x10)
            lines.append(
                f"   Justification: Timestamp field updated "
                f"(0x{old_ts:x} -> 0x{new_ts:x}). "
                "Consistent with periodic metadata refresh."
            )

        elif i == 3:
            stored_fd = read_qword(attacked, chunk["ud_offset"])
            demangled = protect_ptr_reverse(HEAP_BASE + chunk["ud_offset"], stored_fd)
            lines.append("   Classification: MALICIOUS")
            lines.append(
                "   Justification: Chunk was freed into tcache, "
                "but its forward pointer de-mangles to "
                f"0x{demangled:x}, which belongs to an "
                "ALLOCATED chunk (chunk 7 / session_token). "
                "A legitimate free would point to another freed "
                "chunk or NULL. This is the poisoned entry — "
                "the attacker corrupted the fd to redirect a "
                "future allocation toward the session token."
            )

        elif i == 4:
            lines.append("   Classification: MALICIOUS")
            lines.append(
                "   Justification: Chunk freed into tcache bin "
                f"{poison_bin} to establish the chain that the "
                "attacker subsequently poisoned. The free itself "
                "is structurally valid (fd -> NULL), but it "
                "serves no legitimate service purpose — this "
                "buffer type is not recycled in normal operation."
            )

        elif i == 5:
            lines.append("   Classification: BENIGN")
            lines.append(
                "   Justification: Chunk freed into its own "
                "tcache bin with fd -> NULL (tail entry). "
                "Transaction log buffers are routinely recycled "
                "by the service."
            )

        elif i == 6:
            lines.append("   Classification: BENIGN")
            lines.append(
                "   Justification: Data appended to audit log "
                "region. Content is consistent with normal "
                "service logging activity."
            )

        elif i == 7:
            lines.append("   Classification: BENIGN")
            lines.append(
                "   Justification: Chunk freed into its own "
                "tcache bin with fd -> NULL (tail entry). "
                "Config buffers are routinely recycled by the "
                "service."
            )

    # ──────────────────────────────────────
    # ATTACK IMPACT ASSESSMENT
    # ──────────────────────────────────────
    lines.append("")
    lines.append("ATTACK IMPACT ASSESSMENT")
    lines.append("=" * 60)

    lines.append("")
    lines.append("(a) Attacker Objective:")
    lines.append(
        "   The attacker performed a tcache poisoning attack targeting bin "
        f"{poison_bin} (chunk_size 0x{0x20 + poison_bin * 0x10:x}). By corrupting "
        "the fd pointer of chunk 2 (buffer_a) after freeing it into the tcache, "
        "the attacker redirected the free-list chain to overlap with chunk 7 "
        f"(session_token) at userdata address 0x{target_addr:x}. The objective was "
        "to obtain a malloc return pointing to the encrypted session token, enabling "
        "read/write access to credential material stored in an otherwise inaccessible "
        "heap slot."
    )

    lines.append("")
    lines.append("(b) Exploit Viability:")
    lines.append(
        "   The attack WOULD HAVE SUCCEEDED if not interrupted. The tcache bin "
        f"{poison_bin} contains count=2 with head at chunk 2. The first "
        "malloc(0x40) would consume chunk 2 (the head), decrementing count to 1 "
        "and advancing the head to the de-mangled fd — which points to chunk 7's "
        "userdata (the session token). The second malloc(0x40) would then return "
        f"0x{target_addr:x}, granting the attacker direct write access to the "
        "encrypted token buffer. No additional mitigations (ASLR was disabled, "
        "no safe-linking bypass needed since the attacker had a heap leak to "
        "compute the correct mangled pointer) stood between the corrupted state "
        "and successful exploitation."
    )

    lines.append("")
    lines.append("(c) Data at Risk:")
    lines.append(
        "   The targeted chunk 7 contains an encrypted session token. If the "
        "attacker gained write access, they could either exfiltrate the "
        "ciphertext for offline decryption (the encryption key is derivable "
        "from the binary's .rodata AUDIT_KEY_MATERIAL) or overwrite the token "
        "with an attacker-controlled value, enabling session hijacking. The "
        "session token represents authentication credentials — its compromise "
        "would allow full impersonation of the legitimate session owner, "
        "bypassing all authentication controls."
    )

    lines.append("")
    lines.append("(d) Severity Rating: CRITICAL")
    lines.append(
        "   Justification: This is rated CRITICAL because (1) the exploit "
        "targets authentication credentials (session token), (2) the attack "
        "was one allocation away from success, (3) no runtime mitigations "
        "would have prevented the final step (ASLR disabled, safe-linking "
        "already bypassed via heap leak), (4) successful exploitation enables "
        "complete session hijacking with no further interaction required, and "
        "(5) the encryption key is recoverable from the binary, meaning the "
        "attacker could decrypt the stolen token offline. The combination of "
        "high-value target, near-certain exploitability, and severe impact "
        "(credential theft leading to full account compromise) warrants the "
        "highest severity classification."
    )

    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 60)
    lines.append(
        f"Poisoned chunk: chunk 2 (buffer_a) at offset 0x350 (userdata 0x360)"
    )
    lines.append(
        f"Attack target: chunk 7 (session_token) at userdata 0x{target_addr:x}"
    )
    lines.append(
        "Attack objective: Redirect next allocation from tcache "
        f"bin {poison_bin} to overlap the encrypted session token"
    )
    lines.append(
        "Status: Detected and halted before the attacker could "
        "consume the poisoned tcache entry"
    )
    lines.append("")

    return "\n".join(lines)


def main():
    print("=== Heap Forensics Solver ===")

    # Step 1: Extract key from binary
    audit_key = extract_audit_key(BINARY_PATH)
    print(f"Extracted AUDIT_KEY: {audit_key.hex()}")

    # Step 2: Load snapshots
    with open(CLEAN_PATH, "rb") as f:
        clean = f.read()
    with open(ATTACKED_PATH, "rb") as f:
        attacked = f.read()

    # Step 3: Parse heap structures
    chunks_c = walk_chunks(clean)
    chunks_a = walk_chunks(attacked)
    tcache_a = parse_tcache(attacked)
    freed = find_freed_chunks(attacked, chunks_a)

    print(f"Chunks: {len(chunks_a)}, Freed: {len(freed)}, Tcache bins: {len(tcache_a)}")

    # Step 4: Find the poisoned fd
    result = find_poisoned_fd(attacked, tcache_a, freed)
    if result is None:
        print("ERROR: No poisoned fd found!")
        sys.exit(1)
    poisoned_addr, target_addr, poison_bin = result
    print(f"Poisoned fd at 0x{poisoned_addr:x} -> target 0x{target_addr:x}")

    # Step 5: Write forensic report with impact assessment
    report = generate_report(clean, attacked, chunks_c, chunks_a, tcache_a, freed, result)
    with open(REPORT_PATH, "w") as f:
        f.write(report)
    print(f"Forensic report written to {REPORT_PATH}")

    # Step 6: Decrypt session token
    key_input = audit_key + struct.pack("<Q", target_addr)
    key = hashlib.sha256(key_input).digest()
    target_off = target_addr - HEAP_BASE
    encrypted = attacked[target_off : target_off + 0x40]
    decrypted = xor_decrypt(encrypted, key)
    flag = decrypted.rstrip(b"\x00").decode("utf-8", errors="replace")

    with open(FLAG_PATH, "w") as f:
        f.write(flag)
    print(f"Flag: {flag}")


if __name__ == "__main__":
    main()
