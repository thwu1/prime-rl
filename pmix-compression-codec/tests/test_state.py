"""
test_state.py - Verification tests for PPN codec (TAG_BLOB fix + TAG_PACKED + auto-selection)

"""

import subprocess
import os
import pytest


def test_build():
    """Project must build cleanly after changes."""
    result = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"Build failed:\n{result.stderr}"


def test_ppn_test_passes():
    """All round-trip tests in the built-in driver must pass."""
    # Rebuild first to pick up any changes
    subprocess.run(["make", "-C", "/app", "clean", "all"],
                   capture_output=True, timeout=60)
    result = subprocess.run(
        ["/app/ppn_test"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"ppn_test exited with code {result.returncode}:\n{result.stdout}"
    )
    assert "0 failures" in result.stdout, (
        f"Test failures detected:\n{result.stdout}"
    )


def test_tag_packed_defined():
    """TAG_PACKED must be defined in ppn_codec.h."""
    with open("/app/ppn_codec.h") as f:
        header = f.read()
    assert "#define TAG_PACKED" in header, "TAG_PACKED not found in ppn_codec.h"


# ----------------------------------------------------------------
# Comprehensive C verification program
# ----------------------------------------------------------------

VERIFY_SRC = r'''
#include "ppn_codec.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

static int maps_equal(ppn_map_t *a, ppn_map_t *b) {
    if (!a || !b) return 0;
    if (a->total_procs != b->total_procs) return 0;
    if (a->nnodes != b->nnodes) return 0;
    for (int n = 0; n < a->nnodes; n++) {
        if (a->nodes[n].nranks != b->nodes[n].nranks) return 0;
        for (int r = 0; r < a->nodes[n].nranks; r++) {
            if (a->nodes[n].ranks[r] != b->nodes[n].ranks[r]) return 0;
        }
    }
    return 1;
}

static ppn_map_t *make_strided(int nnodes, int rpn, int stride) {
    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;
    int base = 0;
    for (int n = 0; n < nnodes; n++) {
        map->nodes[n].node_id = n;
        map->nodes[n].nranks = rpn;
        map->nodes[n].ranks = calloc(rpn, sizeof(int));
        for (int r = 0; r < rpn; r++)
            map->nodes[n].ranks[r] = base + r * stride;
        base += rpn * stride;
        map->total_procs += rpn;
    }
    return map;
}

static ppn_map_t *make_irregular(int nnodes, int rpn) {
    ppn_map_t *map = ppn_map_alloc(nnodes);
    if (!map) return NULL;
    for (int n = 0; n < nnodes; n++) {
        map->nodes[n].node_id = n;
        map->nodes[n].nranks = rpn;
        map->nodes[n].ranks = calloc(rpn, sizeof(int));
        for (int r = 0; r < rpn; r++)
            map->nodes[n].ranks[r] = r * r + n * rpn * rpn;
        map->total_procs += rpn;
    }
    return map;
}

int main(void) {
    int pass = 0, fail = 0;

    /* ---- Test 1: Direct TAG_BLOB decode (bug-fix verification) ---- */
    {
        char text[32000];
        char *p = text;
        for (int n = 0; n < 3; n++) {
            for (int r = 0; r < 1000; r++) {
                p += sprintf(p, "%d", n * 1000 + r);
                if (r < 999) *p++ = ',';
            }
            if (n < 2) *p++ = ';';
        }
        *p = '\0';
        size_t tlen = (size_t)(p - text);

        uLongf clen = compressBound(tlen);
        uint8_t *comp = malloc(clen);
        if (compress(comp, &clen, (uint8_t *)text, tlen) != Z_OK) {
            printf("FAIL:blob_direct_decode compress_error\n"); fail++;
        } else {
            size_t blen = 1 + 4 + clen;
            uint8_t *buf = malloc(blen);
            buf[0] = 0x02;
            uint32_t orig_sz = (uint32_t)tlen;
            memcpy(buf + 1, &orig_sz, 4);
            memcpy(buf + 5, comp, clen);

            ppn_map_t *dec = ppn_decode(buf, blen);
            int ok = 1;
            if (!dec || dec->total_procs != 3000 || dec->nnodes != 3) ok = 0;
            else {
                for (int nn = 0; ok && nn < 3; nn++) {
                    if (dec->nodes[nn].nranks != 1000) ok = 0;
                    for (int r = 0; ok && r < dec->nodes[nn].nranks; r++)
                        if (dec->nodes[nn].ranks[r] != nn * 1000 + r) ok = 0;
                }
            }
            printf("%s:blob_direct_decode\n", ok ? "PASS" : "FAIL");
            if (ok) pass++; else fail++;
            ppn_map_free(dec);
            free(buf);
        }
        free(comp);
    }

    /* ---- Test 2: Contiguous map → TAG_PACKED (1200 procs) ---- */
    {
        ppn_map_t *orig = ppn_map_generate(1200, 9);
        uint8_t *enc; size_t elen;
        ppn_encode(orig, &enc, &elen);
        int fmt_ok = (enc[0] == 0x03);
        ppn_map_t *dec = ppn_decode(enc, elen);
        int rt_ok = maps_equal(orig, dec);
        int ok = fmt_ok && rt_ok;
        printf("%s:packed_contiguous_1200 fmt=0x%02x sz=%zu rt=%d\n",
               ok ? "PASS" : "FAIL", enc[0], elen, rt_ok);
        if (ok) pass++; else fail++;
        free(enc); ppn_map_free(orig); ppn_map_free(dec);
    }

    /* ---- Test 3: Large contiguous → TAG_PACKED (5000 procs) ---- */
    {
        ppn_map_t *orig = ppn_map_generate(5000, 32);
        uint8_t *enc; size_t elen;
        ppn_encode(orig, &enc, &elen);
        int fmt_ok = (enc[0] == 0x03);
        ppn_map_t *dec = ppn_decode(enc, elen);
        int rt_ok = maps_equal(orig, dec);
        /* Also check every single rank value */
        if (rt_ok && dec) {
            for (int nn = 0; rt_ok && nn < orig->nnodes; nn++) {
                for (int r = 0; rt_ok && r < orig->nodes[nn].nranks; r++) {
                    if (dec->nodes[nn].ranks[r] != orig->nodes[nn].ranks[r])
                        rt_ok = 0;
                }
            }
        }
        int ok = fmt_ok && rt_ok;
        printf("%s:packed_contiguous_5000 fmt=0x%02x sz=%zu rt=%d\n",
               ok ? "PASS" : "FAIL", enc[0], elen, rt_ok);
        if (ok) pass++; else fail++;
        free(enc); ppn_map_free(orig); ppn_map_free(dec);
    }

    /* ---- Test 4: Strided rank roundtrip + compact size ---- */
    {
        ppn_map_t *orig = make_strided(8, 100, 3);
        uint8_t *enc; size_t elen;
        ppn_encode(orig, &enc, &elen);
        ppn_map_t *dec = ppn_decode(enc, elen);
        int rt_ok = maps_equal(orig, dec);
        /* 8 nodes with STRIDED: 1+2+8*(2+1+4+2)=75 bytes.
           Must be well under 200 to confirm STRIDED encoding. */
        int sz_ok = (elen <= 200);
        int ok = rt_ok && sz_ok;
        printf("%s:strided_roundtrip rt=%d sz=%zu szok=%d\n",
               ok ? "PASS" : "FAIL", rt_ok, elen, sz_ok);
        if (ok) pass++; else fail++;
        free(enc); ppn_map_free(orig); ppn_map_free(dec);
    }

    /* ---- Test 5: Explicit (irregular) rank roundtrip ---- */
    {
        ppn_map_t *orig = make_irregular(4, 50);
        uint8_t *enc; size_t elen;
        ppn_encode(orig, &enc, &elen);
        ppn_map_t *dec = ppn_decode(enc, elen);
        int rt_ok = maps_equal(orig, dec);
        printf("%s:explicit_roundtrip rt=%d fmt=0x%02x sz=%zu\n",
               rt_ok ? "PASS" : "FAIL", rt_ok, enc[0], elen);
        if (rt_ok) pass++; else fail++;
        free(enc); ppn_map_free(orig); ppn_map_free(dec);
    }

    /* ---- Test 6: Small map → TAG_RAW ---- */
    {
        ppn_map_t *orig = ppn_map_generate(3, 1);
        uint8_t *enc; size_t elen;
        ppn_encode(orig, &enc, &elen);
        int fmt_ok = (enc[0] == 0x01);
        ppn_map_t *dec = ppn_decode(enc, elen);
        int rt_ok = maps_equal(orig, dec);
        int ok = fmt_ok && rt_ok;
        printf("%s:raw_small_autoselect fmt=0x%02x sz=%zu\n",
               ok ? "PASS" : "FAIL", enc[0], elen);
        if (ok) pass++; else fail++;
        free(enc); ppn_map_free(orig); ppn_map_free(dec);
    }

    /* ---- Test 7: Strided with different stride values ---- */
    {
        ppn_map_t *orig = make_strided(6, 80, 7);
        uint8_t *enc; size_t elen;
        ppn_encode(orig, &enc, &elen);
        ppn_map_t *dec = ppn_decode(enc, elen);
        int rt_ok = maps_equal(orig, dec);
        int sz_ok = (elen <= 200);
        int ok = rt_ok && sz_ok;
        printf("%s:strided_stride7 rt=%d sz=%zu\n",
               ok ? "PASS" : "FAIL", rt_ok, elen);
        if (ok) pass++; else fail++;
        free(enc); ppn_map_free(orig); ppn_map_free(dec);
    }

    printf("\nVERIFICATION:%d_pass_%d_fail\n", pass, fail);
    return fail > 0 ? 1 : 0;
}
'''


@pytest.fixture(scope="module")
def verification_output():
    """Compile and run the comprehensive verification program."""
    # Rebuild first
    build = subprocess.run(
        ["make", "-C", "/app", "clean", "all"],
        capture_output=True, text=True, timeout=60
    )
    assert build.returncode == 0, f"Build failed:\n{build.stderr}"

    verify_src = "/tmp/verify_codec.c"
    verify_bin = "/tmp/verify_codec"

    with open(verify_src, "w") as f:
        f.write(VERIFY_SRC)

    comp = subprocess.run(
        ["gcc", "-Wall", "-O2", "-std=gnu11", "-I/app",
         "-o", verify_bin, verify_src, "/app/ppn_codec.c", "-lz"],
        capture_output=True, text=True, timeout=30
    )
    assert comp.returncode == 0, (
        f"Verification program build failed:\n{comp.stderr}"
    )

    run = subprocess.run(
        [verify_bin], capture_output=True, text=True, timeout=60
    )
    return run.stdout + "\n" + run.stderr


def test_blob_direct_decode(verification_output):
    """TAG_BLOB decoder must correctly handle decompressed rank-list text."""
    assert "PASS:blob_direct_decode" in verification_output, (
        f"TAG_BLOB direct decode failed:\n{verification_output}"
    )


def test_packed_contiguous_1200(verification_output):
    """1200 contiguous procs on 9 nodes must use TAG_PACKED and round-trip."""
    assert "PASS:packed_contiguous_1200" in verification_output, (
        f"Packed contiguous 1200 failed:\n{verification_output}"
    )


def test_packed_contiguous_5000(verification_output):
    """5000 contiguous procs on 32 nodes must use TAG_PACKED and round-trip."""
    assert "PASS:packed_contiguous_5000" in verification_output, (
        f"Packed contiguous 5000 failed:\n{verification_output}"
    )


def test_strided_roundtrip(verification_output):
    """Strided rank maps must round-trip with compact encoding."""
    assert "PASS:strided_roundtrip" in verification_output, (
        f"Strided roundtrip failed:\n{verification_output}"
    )


def test_explicit_roundtrip(verification_output):
    """Irregular (explicit) rank maps must round-trip correctly."""
    assert "PASS:explicit_roundtrip" in verification_output, (
        f"Explicit roundtrip failed:\n{verification_output}"
    )


def test_raw_small_autoselect(verification_output):
    """Small maps must auto-select TAG_RAW (smallest for tiny inputs)."""
    assert "PASS:raw_small_autoselect" in verification_output, (
        f"Raw small autoselect failed:\n{verification_output}"
    )


def test_strided_stride7(verification_output):
    """Strided maps with stride=7 must round-trip with compact encoding."""
    assert "PASS:strided_stride7" in verification_output, (
        f"Strided stride7 failed:\n{verification_output}"
    )


def test_all_verification_pass(verification_output):
    """All sub-tests in the verification program must pass."""
    assert "7_pass_0_fail" in verification_output, (
        f"Not all verification tests passed:\n{verification_output}"
    )
