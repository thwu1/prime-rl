#!/usr/bin/env python3
"""
Generate multi-stage obfuscated challenge files.
Inspired by xz/liblzma backdoor (CVE-2024-3094) obfuscation techniques.

Creates a simulated compromised project with a hidden payload extracted through:
  Stage 0: tr byte-swap cipher on corrupted xz stream
  Stage 1: head-chain data interleaving + tr substitution cipher
  Stage 2: AWK-implemented modified RC4 stream cipher (addition mod 256)

Also creates benign-but-suspicious red herring files for forensic triage.
"""
import hashlib
import lzma
import os
import stat

# ===== DETERMINISTIC PARAMETERS =====
SEED = b"terminal-bench-multistage-deobfuscation-xz-style-2024"
PAYLOAD_SIZE = 4096

# RC4 variant parameters (used in Stage 2 AWK cipher)
RC4_K_MULT = 11
RC4_K_ADD = 3
RC4_SKIP = 6144

# Interleaving parameters
PAD_SIZE = 128
DATA_BLOCK_SIZE = 256
PAD_BYTE = 0x41  # 'A'

# TR cipher ranges for Stage 1->2 decryption
# tr "FROM" "\0-\377" decrypts
STAGE1_RANGES = [(12, 51), (100, 255), (52, 75), (86, 99), (0, 11), (76, 85)]
STAGE1_TR_FROM = r'\14-\63\144-\377\64-\113\126-\143\0-\13\114-\125'

# Stage 0: simple 4-byte swap (tab<->space, dash<->underscore)
STAGE0_SWAP = {0x09: 0x20, 0x20: 0x09, 0x2D: 0x5F, 0x5F: 0x2D}


def deterministic_bytes(n, extra=b""):
    result = bytearray()
    counter = 0
    while len(result) < n:
        h = hashlib.sha256(SEED + extra + counter.to_bytes(4, 'big'))
        result.extend(h.digest())
        counter += 1
    return bytes(result[:n])


def make_encrypt_table(ranges):
    table = []
    for start, end in ranges:
        table.extend(range(start, end + 1))
    assert len(table) == 256, f"Range total {len(table)} != 256"
    return bytes(table)


def make_decrypt_table(ranges):
    encrypt = make_encrypt_table(ranges)
    decrypt = [0] * 256
    for i, v in enumerate(encrypt):
        decrypt[v] = i
    return bytes(decrypt)


def apply_table(data, table):
    return bytes(table[b] for b in data)


def apply_swap(data, swap_map):
    return bytes(swap_map.get(b, b) for b in data)


def xz_compress(data):
    return lzma.compress(data, format=lzma.FORMAT_XZ, check=lzma.CHECK_NONE)


def lzma_compress_alone(data):
    return lzma.compress(data, format=lzma.FORMAT_ALONE)


def rc4_encrypt(data, k_mult, k_add, skip):
    """Encrypt so AWK (v+k)%m decrypts."""
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
        result.append((byte - k + m) % m)
    return bytes(result)


def rc4_decrypt(data, k_mult, k_add, skip):
    """Verify: plaintext = (ciphertext + keystream) % 256"""
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


def interleave(data, pad_size, block_size, pad_byte=0x41):
    result = bytearray()
    offset = 0
    while offset < len(data):
        result.extend(bytes([pad_byte]) * pad_size)
        chunk = data[offset:offset + block_size]
        result.extend(chunk)
        offset += block_size
    return bytes(result)


def deinterleave(data, pad_size, block_size):
    result = bytearray()
    offset = 0
    while offset < len(data):
        offset += pad_size
        if offset >= len(data):
            break
        chunk_size = min(block_size, len(data) - offset)
        result.extend(data[offset:offset + chunk_size])
        offset += chunk_size
    return bytes(result)


def generate_head_chain(total_data_len, pad_size, block_size):
    parts = []
    remaining = total_data_len
    while remaining > 0:
        parts.append(f"(head -c +{pad_size} >/dev/null)")
        take = min(block_size, remaining)
        parts.append(f"head -c +{take}")
        remaining -= take
    return " && ".join(parts)


def main():
    outdir = "/app/project"

    # 1. Generate payload
    payload = deterministic_bytes(PAYLOAD_SIZE, b"payload")
    payload_sha256 = hashlib.sha256(payload).hexdigest()

    # 2. Compress payload with xz
    payload_xz = xz_compress(payload)

    # 3. RC4-encrypt compressed payload
    payload_rc4 = rc4_encrypt(payload_xz, RC4_K_MULT, RC4_K_ADD, RC4_SKIP)

    # Verify decryption roundtrip
    assert lzma.decompress(
        rc4_decrypt(payload_rc4, RC4_K_MULT, RC4_K_ADD, RC4_SKIP),
        format=lzma.FORMAT_XZ
    ) == payload

    # 4. Create Stage 2 script
    stage2_script = (
        '####Payload####\n'
        '# Stage 2: Extract hidden payload\n'
        'N=0\n'
        f'W={len(payload)}\n'
        'p="good-archive.lzma"\n'
        'xz -dc $top_srcdir/tests/files/$p | eval $i | '
        'LC_ALL=C sed "s/\\(.\\)/\\1\\n/g" | '
        "LC_ALL=C awk '"
        'BEGIN{FS="\\n";RS="\\n";ORS="";m=256;'
        f'for(i=0;i<m;i++){{t[sprintf("x%c",i)]=i;c[i]=((i*{RC4_K_MULT})+{RC4_K_ADD})%m;}}'
        f'i=0;j=0;for(l=0;l<{RC4_SKIP};l++){{i=(i+1)%m;a=c[i];j=(j+a)%m;c[i]=c[j];c[j]=a;}}}}'
        '{v=t["x" (NF<1?RS:$1)];i=(i+1)%m;a=c[i];j=(j+a)%m;b=c[j];c[i]=b;c[j]=a;'
        "k=c[(a+b)%m];printf \"%c\",(v+k)%m}'"
        ' | xz -dc --single-stream | '
        '((head -c +$N > /dev/null 2>&1) && head -c +$W) > /tmp/extracted_payload.bin\n'
        '####End####\n'
    ).encode()

    # 5. Compress Stage 2 with xz
    stage2_xz = xz_compress(stage2_script)

    # 6. Apply Stage 1 substitution cipher to compressed Stage 2
    stage1_encrypt = make_encrypt_table(STAGE1_RANGES)
    stage2_ciphered = apply_table(stage2_xz, stage1_encrypt)

    # 7. Combine RC4 ciphertext + tr-ciphered Stage 2
    combined = payload_rc4 + stage2_ciphered
    tail_offset = len(payload_rc4) + 1  # tail -c +N starts at byte N

    # 8. Interleave with padding
    interleaved = interleave(combined, PAD_SIZE, DATA_BLOCK_SIZE)

    # Verify deinterleaving
    assert deinterleave(interleaved, PAD_SIZE, DATA_BLOCK_SIZE)[:len(combined)] == combined

    # 9. Generate head chain
    head_chain = generate_head_chain(len(combined), PAD_SIZE, DATA_BLOCK_SIZE)

    # 10. LZMA-compress interleaved data
    good_archive = lzma_compress_alone(interleaved)

    # 11. Create Stage 1 script
    stage1_script = (
        '####Hello####\n'
        f'export i="({head_chain})"\n'
        f'(xz -dc $srcdir/tests/files/good-archive.lzma|eval $i|tail -c +{tail_offset}|'
        f'tr "{STAGE1_TR_FROM}" "\\0-\\377")|xz -dc|/bin/sh\n'
        '####World####\n'
    ).encode()

    # 12. XZ-compress Stage 1
    stage1_xz = xz_compress(stage1_script)

    # 13. Apply Stage 0 byte swap + append marker
    bad_stream_core = apply_swap(stage1_xz, STAGE0_SWAP)
    bad_stream = bad_stream_core + b"####World####\n"

    # Verify full roundtrip
    fixed = apply_swap(bad_stream_core, STAGE0_SWAP)
    assert lzma.decompress(fixed, format=lzma.FORMAT_XZ) == stage1_script

    decompressed_archive = lzma.decompress(good_archive, format=lzma.FORMAT_ALONE)
    extracted = deinterleave(decompressed_archive, PAD_SIZE, DATA_BLOCK_SIZE)[:len(combined)]
    s1_decrypt = make_decrypt_table(STAGE1_RANGES)
    s2_dec = apply_table(extracted[len(payload_rc4):], s1_decrypt)
    assert lzma.decompress(s2_dec, format=lzma.FORMAT_XZ) == stage2_script
    rc4_dec = rc4_decrypt(extracted[:len(payload_rc4)], RC4_K_MULT, RC4_K_ADD, RC4_SKIP)
    assert lzma.decompress(rc4_dec, format=lzma.FORMAT_XZ) == payload

    # ===== WRITE CHALLENGE FILES =====
    os.makedirs(f"{outdir}/m4", exist_ok=True)
    os.makedirs(f"{outdir}/tests/files", exist_ok=True)
    os.makedirs(f"{outdir}/tests/fixtures", exist_ok=True)
    os.makedirs(f"{outdir}/src", exist_ok=True)
    os.makedirs(f"{outdir}/scripts", exist_ok=True)

    # M4 build macro (Stage 0 entry point) — BACKDOOR
    m4_content = '''# build-to-host.m4 serial 30
# Patched configuration macro for host-specific builds
dnl Copyright (C) 2023-2024 Software Foundation
dnl This file is free software

AC_DEFUN([gl_BUILD_TO_HOST],
[
  dnl Set up host-specific build configuration
  gl_cv_host_system_type="$host"

  # Auto-detect configuration file
  gl_am_configmake=`grep -aErls "#{4}[[:alnum:]]{5}#{4}$" $srcdir/tests/files/ 2>/dev/null`
  if test "x$gl_am_configmake" != "x"; then
    gl_[$1]_prefix=xz
    gl_path_map='tr "\\t \\-_" " \\t_\\-"'
    gl_[$1]_config='cat $gl_am_configmake | eval $gl_path_map | $gl_[$1]_prefix -d 2>/dev/null'
  fi

  if test -n "$gl_[$1]_config"; then
    eval $gl_[$1]_config
  fi
])
'''
    with open(f"{outdir}/m4/build-to-host.m4", "w") as f:
        f.write(m4_content)

    # Binary test files — BACKDOOR data
    with open(f"{outdir}/tests/files/bad-stream.xz", "wb") as f:
        f.write(bad_stream)

    with open(f"{outdir}/tests/files/good-archive.lzma", "wb") as f:
        f.write(good_archive)

    # ===== RED HERRING FILES (benign but suspicious-looking) =====

    # Red herring 1: autoconf macro with eval and complex shell — BENIGN
    ax_macro = r'''# ax_check_compile_flag.m4 serial 18
# ===========================================================================
#    https://www.gnu.org/software/autoconf-archive/ax_check_compile_flag.html
# ===========================================================================
#
# SYNOPSIS
#   AX_CHECK_COMPILE_FLAG(FLAG, [ACTION-SUCCESS], [ACTION-FAILURE], [EXTRA-FLAGS], [INPUT])
#
# DESCRIPTION
#   Check whether the given FLAG works with the current language's compiler.
#   Caches result and supports optional extra flags and custom test input.

AC_DEFUN([AX_CHECK_COMPILE_FLAG], [
  AS_VAR_PUSHDEF([CACHEVAR], [ax_cv_check_[]_AC_LANG_ABBREV[]flags_$4_$1])
  AC_CACHE_CHECK([whether _AC_LANG compiler accepts $1], CACHEVAR, [
    ax_check_save_flags=$[]_AC_LANG_PREFIX[]FLAGS
    _AC_LANG_PREFIX[]FLAGS="$[]_AC_LANG_PREFIX[]FLAGS $4 $1"
    AC_COMPILE_IFELSE([m4_default([$5],[AC_LANG_PROGRAM()])],
      [AS_VAR_SET(CACHEVAR,[yes])],
      [AS_VAR_SET(CACHEVAR,[no])])
    _AC_LANG_PREFIX[]FLAGS=$ax_check_save_flags])
  AS_VAR_IF(CACHEVAR,yes,
    [m4_default([$2], :)],
    [m4_default([$3], :)])
  AS_VAR_POPDEF([CACHEVAR])
])

dnl Configure optimal build flags for the current platform
AC_DEFUN([AX_CONFIGURE_OPTFLAGS], [
  gl_cv_optflags=""
  for flag in -O3 -march=native -flto -fomit-frame-pointer -fvisibility=hidden; do
    AX_CHECK_COMPILE_FLAG([$flag], [
      eval "gl_cv_optflags=\"\$gl_cv_optflags $flag\""
    ])
  done
  dnl Apply accumulated flags
  AC_SUBST([OPTFLAGS], [$gl_cv_optflags])
])
'''
    with open(f"{outdir}/m4/ax_check_compile_flag.m4", "w") as f:
        f.write(ax_macro)

    # Red herring 2: shell script using eval, tr, awk — BENIGN
    gen_corpus = r'''#!/bin/bash
# Generate deterministic test corpus for compression ratio benchmarks.
# Creates controlled-entropy binary data for reproducible codec testing.
# Usage: gen-corpus.sh [output-dir]
set -e

OUTDIR="${1:-tests/fixtures}"
SEED="libcompress-test-corpus-v2.8.1"
NBLOCKS=64
BLOCKSIZE=256

mkdir -p "$OUTDIR"

# Use eval to run inline python and capture its status output
eval "$(python3 -c "
import hashlib, struct, sys
seed = b'$SEED'
out = bytearray()
for b in range($NBLOCKS):
    for i in range($BLOCKSIZE):
        h = hashlib.sha256(seed + struct.pack('>II', b, i)).digest()
        out.append(h[0])
with open('$OUTDIR/entropy_test.dat', 'wb') as f:
    f.write(bytes(out))
print('echo GENERATED=OK')
")"

# Post-generation integrity verification
HASH=$(sha256sum "$OUTDIR/entropy_test.dat" | tr -s ' ' | cut -d' ' -f1)

# Format and display summary using awk
echo "$((NBLOCKS * BLOCKSIZE)) $HASH" | \
    awk '{printf "Generated %d bytes of test data\nSHA-256: %s\n", $1, $2}'
'''
    with open(f"{outdir}/scripts/gen-corpus.sh", "w") as f:
        f.write(gen_corpus)
    os.chmod(f"{outdir}/scripts/gen-corpus.sh",
             stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)

    # Red herring 3: high-entropy binary test data — BENIGN
    # Deterministic PRNG output used for compression ratio testing
    test_seed = b'libcompress-test-corpus-v2.8.1'
    test_data = bytearray()
    for block in range(64):
        for i in range(256):
            h = hashlib.sha256(
                test_seed + block.to_bytes(4, 'big') + i.to_bytes(4, 'big')
            )
            test_data.append(h.digest()[0])
    with open(f"{outdir}/tests/fixtures/entropy_test.dat", "wb") as f:
        f.write(bytes(test_data))

    # ===== STANDARD PROJECT FILES (clearly benign) =====

    with open(f"{outdir}/configure.ac", "w") as f:
        f.write('''AC_INIT([libcompress], [2.8.1])
AC_CONFIG_MACRO_DIRS([m4])
AM_INIT_AUTOMAKE
AC_PROG_CC
AC_PROG_LIBTOOL
m4_include([m4/build-to-host.m4])
m4_include([m4/ax_check_compile_flag.m4])
gl_BUILD_TO_HOST([localedir])
AX_CONFIGURE_OPTFLAGS
AC_OUTPUT
''')

    with open(f"{outdir}/Makefile.am", "w") as f:
        f.write('''lib_LTLIBRARIES = libcompress.la
libcompress_la_SOURCES = src/compress.c src/decompress.c src/crc64.c
libcompress_la_LDFLAGS = -version-info 5:1:0
TESTS = tests/test_basic tests/test_crc
check_PROGRAMS = tests/test_basic tests/test_crc
''')

    with open(f"{outdir}/src/compress.c", "w") as f:
        f.write('''/* libcompress - high-performance compression library */
#include <stdlib.h>
#include <string.h>

int lc_compress(const unsigned char *in, size_t in_len,
                unsigned char *out, size_t *out_len) {
    size_t i = 0, j = 0;
    while (i < in_len && j + 2 < *out_len) {
        unsigned char c = in[i];
        size_t run = 1;
        while (i + run < in_len && in[i + run] == c && run < 255) run++;
        out[j++] = (unsigned char)run;
        out[j++] = c;
        i += run;
    }
    *out_len = j;
    return (i == in_len) ? 0 : -1;
}
''')

    with open(f"{outdir}/src/decompress.c", "w") as f:
        f.write('''/* libcompress - decompression routines */
#include <stdlib.h>
#include <string.h>

int lc_decompress(const unsigned char *in, size_t in_len,
                  unsigned char *out, size_t *out_len) {
    size_t i = 0, j = 0;
    while (i + 1 < in_len && j < *out_len) {
        unsigned char run = in[i++];
        unsigned char c = in[i++];
        for (size_t k = 0; k < run && j < *out_len; k++)
            out[j++] = c;
    }
    *out_len = j;
    return 0;
}
''')

    with open(f"{outdir}/src/crc64.c", "w") as f:
        f.write('''/* libcompress - CRC-64 fast implementation */
#include <stdint.h>
#include <stddef.h>

static const uint64_t crc64_table[256] = {0};

uint64_t lc_crc64(const uint8_t *buf, size_t len) {
    uint64_t crc = ~0ULL;
    for (size_t i = 0; i < len; i++)
        crc = crc64_table[(crc ^ buf[i]) & 0xFF] ^ (crc >> 8);
    return ~crc;
}
''')

    # config.status for srcdir resolution
    with open(f"{outdir}/config.status", "w") as f:
        f.write("srcdir='.'\n")


if __name__ == "__main__":
    main()
