#!/usr/bin/env python3
"""
Security audit, hardened allocator design, and defense evaluation solver.

1. Analyzes C source for vulnerability patterns
2. Designs a hardened pool allocator with canary/quarantine/poison
3. Patches the codebase integrating the hardened allocator + individual fixes
4. Produces a defense assessment with severity ranking and chain analysis
"""

import json
import os
import re
import shutil
import subprocess

SRC_DIR    = "/app/src"
REPORT     = "/app/audit_report.json"
PATCH_DIR  = "/app/patched"
HARDEN_DIR = "/app/hardened_pool"
ASSESS     = "/app/defense_assessment.json"


def read_file(path):
    with open(path) as f:
        return f.read()


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def extract_function(source, name):
    pat = rf"(?:static\s+)?[\w_][\w_\s\*]*\b{re.escape(name)}\s*\([^)]*\)\s*\{{"
    m = re.search(pat, source)
    if not m:
        return ""
    depth, start = 0, m.start()
    for i in range(m.end() - 1, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    return ""


# ------------------------------------------------------------------ #
#  Analysis — identify vulnerabilities by pattern matching            #
# ------------------------------------------------------------------ #

def analyze(handlers_src, headers_src):
    vulns = []

    # --- 1. heap-buffer-overflow in handle_store_data ---
    fn = extract_function(handlers_src, "handle_store_data")
    if fn:
        has_memcpy = "memcpy(entry->data," in fn
        has_check  = re.search(r"data_len\s*[><]=?\s*STORE_BUFFER_SIZE", fn)
        if has_memcpy and not has_check:
            buf_m = re.search(r"#define\s+STORE_BUFFER_SIZE\s+(\d+)", headers_src)
            bsz = buf_m.group(1) if buf_m else "?"
            vulns.append({
                "id": "VULN-001",
                "type": "heap-buffer-overflow",
                "cwe": "CWE-122",
                "command": "CMD_STORE_DATA",
                "function": "handle_store_data",
                "file": "handlers.c",
                "root_cause": (
                    f"memcpy copies data_len bytes (derived from payload_length) "
                    f"into entry->data which is only {bsz} bytes, with no bounds check"
                ),
                "trigger": "Send CMD_STORE_DATA with payload_length > STORE_BUFFER_SIZE + 4",
                "severity_score": 8,
                "exploitation_class": "arbitrary-write",
            })

    # --- 2. stack-buffer-overflow in format_log_entry ---
    fn_log = extract_function(handlers_src, "handle_log_event")
    fn_fmt = extract_function(handlers_src, "format_log_entry")
    if fn_log and fn_fmt:
        uses_wrong_const = "MAX_LOG_PREFIX" in fn_log
        has_stack_buf = re.search(r"char\s+\w+\[LOG_ENTRY_BUFFER\]", fn_log)
        raw_memcpy = "memcpy(output + written, message, msg_len)" in fn_fmt
        if uses_wrong_const and has_stack_buf and raw_memcpy:
            vulns.append({
                "id": "VULN-002",
                "type": "stack-buffer-overflow",
                "cwe": "CWE-121",
                "command": "CMD_LOG_EVENT",
                "function": "format_log_entry",
                "file": "handlers.c",
                "root_cause": (
                    "msg_len is validated against MAX_LOG_PREFIX (256) but the "
                    "destination buffer is LOG_ENTRY_BUFFER (64) bytes on the stack; "
                    "format_log_entry copies msg_len bytes via memcpy without "
                    "respecting output_size"
                ),
                "trigger": "Send CMD_LOG_EVENT with msg_len between 64 and 256",
                "severity_score": 9,
                "exploitation_class": "code-execution",
            })

    # --- 3. use-after-free in handle_manage_session ---
    fn_ses = extract_function(handlers_src, "handle_manage_session")
    fn_rel = extract_function(handlers_src, "release_session_resources")
    if fn_ses and fn_rel:
        frees_stats  = "pool_free(ctx->stats" in fn_rel
        nulls_stats  = re.search(r"ctx->stats\s*=\s*NULL", fn_rel)
        reads_stats  = "g_current_session->stats" in fn_ses
        if frees_stats and not nulls_stats and reads_stats:
            vulns.append({
                "id": "VULN-003",
                "type": "use-after-free",
                "cwe": "CWE-416",
                "command": "CMD_MANAGE_SESSION",
                "function": "handle_manage_session",
                "file": "handlers.c",
                "root_cause": (
                    "release_session_resources frees ctx->stats but does not "
                    "nullify the pointer; a subsequent SUBCMD_SESSION_STATS "
                    "dereferences the dangling pointer"
                ),
                "trigger": "Send SESSION_CREATE, SESSION_RESET, SESSION_STATS in sequence",
                "severity_score": 8,
                "exploitation_class": "arbitrary-read",
            })

    # --- 4. double-free in handle_cleanup_txn ---
    fn_txn = extract_function(handlers_src, "handle_cleanup_txn")
    fn_cb  = extract_function(handlers_src, "txn_cleanup_callback")
    if fn_txn and fn_cb:
        rb_idx = fn_txn.find("SUBCMD_TXN_ROLLBACK")
        if rb_idx >= 0:
            rb_body = fn_txn[rb_idx:]
            frees_buf = "pool_free(g_current_txn->data_buf" in rb_body
            calls_cb  = "cleanup_fn" in rb_body
            null_before = re.search(
                r"pool_free\(g_current_txn->data_buf.*?\n.*?data_buf\s*=\s*NULL.*?cleanup_fn",
                rb_body, re.DOTALL,
            )
            cb_also_frees = "pool_free(txn->data_buf" in fn_cb
            if frees_buf and calls_cb and cb_also_frees and not null_before:
                vulns.append({
                    "id": "VULN-004",
                    "type": "double-free",
                    "cwe": "CWE-415",
                    "command": "CMD_CLEANUP_TXN",
                    "function": "handle_cleanup_txn",
                    "file": "handlers.c",
                    "root_cause": (
                        "ROLLBACK frees data_buf then invokes cleanup_fn "
                        "(txn_cleanup_callback) which frees data_buf again "
                        "because the pointer was not nullified between the two frees"
                    ),
                    "trigger": "Send TXN_BEGIN with data, then TXN_ROLLBACK",
                    "severity_score": 7,
                    "exploitation_class": "arbitrary-write",
                })

    # --- 5. integer-overflow in handle_batch_alloc ---
    fn_ba = extract_function(handlers_src, "handle_batch_alloc")
    if fn_ba:
        has_mult = re.search(
            r"uint32_t\s+\w+\s*=\s*req->count\s*\*\s*req->item_size", fn_ba
        )
        has_guard = re.search(r"UINT32_MAX|0xFFFFFFFF", fn_ba)
        if has_mult and not has_guard:
            vulns.append({
                "id": "VULN-005",
                "type": "integer-overflow",
                "cwe": "CWE-190",
                "command": "CMD_BATCH_ALLOC",
                "function": "handle_batch_alloc",
                "file": "handlers.c",
                "root_cause": (
                    "count * item_size is computed in uint32_t; when the product "
                    "exceeds 2^32 it wraps to a small value, causing a too-small "
                    "allocation while the subsequent memcpy uses the real payload length"
                ),
                "trigger": (
                    "Send CMD_BATCH_ALLOC with count=0x10000 item_size=0x10000 "
                    "plus extra payload bytes"
                ),
                "severity_score": 8,
                "exploitation_class": "arbitrary-write",
            })

    # --- 6. type-confusion in handle_process_packet ---
    fn_pp = extract_function(handlers_src, "handle_process_packet")
    if fn_pp:
        sets_cb   = "process_cb = default_packet_handler" in fn_pp
        sets_type = "packet_type = user_packet_type" in fn_pp
        calls_cb  = "process_cb(" in fn_pp
        if sets_cb and sets_type and calls_cb:
            pos_cb   = fn_pp.find("process_cb =")
            pos_type = fn_pp.find("packet_type =")
            pos_call = fn_pp.find("process_cb(")
            if pos_cb < pos_type < pos_call:
                vulns.append({
                    "id": "VULN-006",
                    "type": "type-confusion",
                    "cwe": "CWE-843",
                    "command": "CMD_PROCESS_PACKET",
                    "function": "handle_process_packet",
                    "file": "handlers.c",
                    "root_cause": (
                        "packet_object_t uses a union where packet_type (uint32_t) "
                        "and process_cb (function pointer) share memory; writing "
                        "packet_type after setting process_cb corrupts the function "
                        "pointer, which is subsequently called"
                    ),
                    "trigger": (
                        "Send CMD_PROCESS_PACKET with flags=0x0101 and a crafted "
                        "packet_type value"
                    ),
                    "severity_score": 9,
                    "exploitation_class": "code-execution",
                })

    # --- 7. out-of-bounds in handle_read_config ---
    fn_rc = extract_function(handlers_src, "handle_read_config")
    if fn_rc:
        idx_access = "entries[req->index]" in fn_rc
        has_bound  = re.search(
            r"req->index\s*[><]=?\s*(CONFIG_MAX_ENTRIES|\d+)", fn_rc
        )
        if idx_access and not has_bound:
            vulns.append({
                "id": "VULN-007",
                "type": "out-of-bounds",
                "cwe": "CWE-787",
                "command": "CMD_READ_CONFIG",
                "function": "handle_read_config",
                "file": "handlers.c",
                "root_cause": (
                    "User-supplied req->index is used to access g_config.entries[] "
                    "(max 16 entries) without any bounds validation"
                ),
                "trigger": "Send CMD_READ_CONFIG with index >= 16",
                "severity_score": 6,
                "exploitation_class": "arbitrary-read",
            })

    return vulns


# ------------------------------------------------------------------ #
#  Hardened pool allocator — create from scratch                     #
# ------------------------------------------------------------------ #

HARDENED_POOL_H = r"""#ifndef POOL_H
#define POOL_H

#include <stdint.h>
#include <stddef.h>

#define POOL_TAG(a,b,c,d) \
    ((uint32_t)(a) | ((uint32_t)(b)<<8) | ((uint32_t)(c)<<16) | ((uint32_t)(d)<<24))

typedef struct pool_header {
    uint32_t tag;
    uint32_t size;
    struct pool_header *next;
} pool_header_t;

void *pool_alloc(uint32_t pool_type, size_t size, uint32_t tag);
void  pool_free(void *ptr, uint32_t tag);
void  pool_dump_stats(void);

#define POOL_PAGED    0
#define POOL_NONPAGED 1

#endif
"""

HARDENED_POOL_C = r"""/*
 * Hardened pool allocator with canary, quarantine, and poison mechanisms.
 *
 * Defense mechanisms:
 *   1. CANARY: A trailing sentinel word is written after each allocation.
 *      On free, the canary is verified to detect buffer overflows.
 *   2. QUARANTINE: Freed blocks are held in a ring buffer rather than
 *      returned to the system allocator immediately. This prevents
 *      use-after-free exploitation by delaying memory reuse, and
 *      detects double-free by checking quarantine membership.
 *   3. POISON: Freed memory is overwritten with 0xDE bytes to make
 *      use-after-free reads return garbage rather than stale data.
 */
#include "pool.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

/* ---- Canary configuration ---- */
#define CANARY_MAGIC 0xDEADCAFEu

/* ---- Quarantine configuration ---- */
#define QUARANTINE_SLOTS 64
#define POISON_BYTE 0xDE

/* Internal extended header — not exposed via pool.h */
typedef struct hpool_header {
    uint32_t tag;
    uint32_t size;           /* user-requested size */
    struct hpool_header *next;
    uint32_t canary_seed;    /* expected trailing canary value */
} hpool_header_t;

/* Quarantine ring buffer entry */
typedef struct {
    hpool_header_t *hdr;
    size_t total_alloc;
} quarantine_entry_t;

static hpool_header_t *alloc_list = NULL;
static int total_allocs = 0;
static int total_frees = 0;

static quarantine_entry_t quarantine_ring[QUARANTINE_SLOTS];
static int q_head  = 0;
static int q_count = 0;

/* Compute a deterministic canary from tag and size */
static uint32_t compute_canary(uint32_t tag, uint32_t sz) {
    return CANARY_MAGIC ^ tag ^ (sz * 0x01000193u);
}

/* Pointer to trailing canary word after user data */
static uint32_t *trailing_canary_ptr(hpool_header_t *h) {
    return (uint32_t *)((char *)(h + 1) + h->size);
}

/* Check if a header is currently in the quarantine (double-free detection) */
static int quarantine_contains(hpool_header_t *h) {
    for (int i = 0; i < q_count; i++) {
        int idx = (q_head - q_count + i + QUARANTINE_SLOTS) % QUARANTINE_SLOTS;
        if (quarantine_ring[idx].hdr == h)
            return 1;
    }
    return 0;
}

/* Evict the oldest quarantine entry to make room */
static void quarantine_evict(void) {
    if (q_count >= QUARANTINE_SLOTS) {
        int oldest = (q_head - q_count + QUARANTINE_SLOTS) % QUARANTINE_SLOTS;
        free(quarantine_ring[oldest].hdr);
        quarantine_ring[oldest].hdr = NULL;
        q_count--;
    }
}

/* Push a freed block into the quarantine ring */
static void quarantine_push(hpool_header_t *h, size_t total) {
    quarantine_evict();
    quarantine_ring[q_head].hdr = h;
    quarantine_ring[q_head].total_alloc = total;
    q_head = (q_head + 1) % QUARANTINE_SLOTS;
    q_count++;
}

void *pool_alloc(uint32_t pool_type, size_t size, uint32_t tag) {
    (void)pool_type;

    /* Layout: [hpool_header_t] [user data: size bytes] [canary: 4 bytes] */
    size_t total = sizeof(hpool_header_t) + size + sizeof(uint32_t);
    hpool_header_t *hdr = (hpool_header_t *)malloc(total);
    if (!hdr) return NULL;

    hdr->tag         = tag;
    hdr->size        = (uint32_t)size;
    hdr->canary_seed = compute_canary(tag, (uint32_t)size);
    hdr->next        = alloc_list;
    alloc_list       = hdr;
    total_allocs++;

    void *data = (void *)(hdr + 1);
    memset(data, 0, size);

    /* Write trailing canary sentinel */
    *trailing_canary_ptr(hdr) = hdr->canary_seed;

    return data;
}

void pool_free(void *ptr, uint32_t tag) {
    (void)tag;
    if (!ptr) return;

    hpool_header_t *hdr = ((hpool_header_t *)ptr) - 1;

    /* DEFENSE: double-free detection via quarantine lookup */
    if (quarantine_contains(hdr)) {
        fprintf(stderr, "[pool-hardened] DOUBLE-FREE detected tag=0x%08x\n",
                hdr->tag);
        return;
    }

    /* DEFENSE: canary verification for overflow detection */
    uint32_t expected = compute_canary(hdr->tag, hdr->size);
    uint32_t actual   = *trailing_canary_ptr(hdr);
    if (actual != expected) {
        fprintf(stderr,
                "[pool-hardened] CANARY CORRUPTION detected tag=0x%08x "
                "(expected=0x%08x actual=0x%08x)\n",
                hdr->tag, expected, actual);
    }

    /* Remove from active allocation list */
    hpool_header_t **pp = &alloc_list;
    while (*pp) {
        if (*pp == hdr) {
            *pp = hdr->next;
            break;
        }
        pp = &(*pp)->next;
    }
    total_frees++;

    /* DEFENSE: poison freed memory to surface UAF reads */
    memset(ptr, POISON_BYTE, hdr->size);

    /* DEFENSE: quarantine — delay reuse to prevent UAF exploitation */
    size_t total = sizeof(hpool_header_t) + hdr->size + sizeof(uint32_t);
    quarantine_push(hdr, total);
}

void pool_dump_stats(void) {
    fprintf(stderr,
            "[pool-hardened] allocs=%d frees=%d outstanding=%d quarantine=%d/%d\n",
            total_allocs, total_frees, total_allocs - total_frees,
            q_count, QUARANTINE_SLOTS);
}
"""


# ------------------------------------------------------------------ #
#  Patching — apply hardened allocator + individual fixes            #
# ------------------------------------------------------------------ #

def patch_handlers(src):
    lines = src.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # FIX 1: bounds check before memcpy in handle_store_data
        if "entry->data_len = data_len;" in line and "memcpy(entry->data" in lines[i + 1]:
            out.append("    if (data_len > STORE_BUFFER_SIZE) {")
            out.append('        fprintf(stderr, "[store] data exceeds buffer\\n");')
            out.append("        pool_free(entry, POOL_TAG('S','t','o','r'));")
            out.append("        return -1;")
            out.append("    }")
            out.append(line)  # entry->data_len = data_len;
            i += 1
            continue

        # FIX 2a: fix validation constant in handle_log_event
        if "evt->msg_len > MAX_LOG_PREFIX" in line:
            out.append(line.replace("MAX_LOG_PREFIX", "LOG_ENTRY_BUFFER - 10"))
            i += 1
            continue

        # FIX 2b: respect output_size in format_log_entry
        if "memcpy(output + written, message, msg_len);" in line:
            out.append("    size_t avail = ((size_t)written < output_size) "
                       "? output_size - (size_t)written - 1 : 0;")
            out.append("    size_t clen = (msg_len < avail) ? msg_len : avail;")
            out.append("    memcpy(output + written, message, clen);")
            if i + 1 < len(lines) and "output[written + msg_len]" in lines[i + 1]:
                out.append("    output[written + clen] = '\\0';")
                if i + 2 < len(lines) and "return written + msg_len" in lines[i + 2]:
                    out.append("    return written + (int)clen;")
                    i += 3
                    continue
                i += 2
                continue
            i += 1
            continue

        # FIX 3: nullify stats after free in release_session_resources
        if "pool_free(ctx->stats, POOL_TAG('S','s','t','a'));" in line:
            out.append(line)
            out.append("        ctx->stats = NULL;")
            i += 1
            continue

        # FIX 3b: guard stats access in SESSION_STATS
        if "session_stats_t *s = g_current_session->stats;" in line:
            out.append(line)
            out.append("            if (!s) {")
            out.append('                fprintf(stderr, '
                       '"[session] stats unavailable\\n");')
            out.append("                return -1;")
            out.append("            }")
            i += 1
            continue

        # FIX 4: nullify data_buf before cleanup in ROLLBACK
        if ("pool_free(g_current_txn->data_buf, POOL_TAG('T','d','a','t'));"
                in line and i + 1 < len(lines)
                and "}" in lines[i + 1]
                and any("cleanup_fn" in lines[j]
                        for j in range(i + 2, min(i + 6, len(lines))))):
            out.append(line)
            out.append("                g_current_txn->data_buf = NULL;")
            i += 1
            continue

        # FIX 5: integer overflow guard in handle_batch_alloc
        if "uint32_t total_data = req->count * req->item_size;" in line:
            out.append("    if (req->item_size > 0 "
                       "&& req->count > (uint32_t)0xFFFFFFFF / req->item_size) {")
            out.append('        fprintf(stderr, '
                       '"[batch] integer overflow detected\\n");')
            out.append("        return -1;")
            out.append("    }")
            out.append(line)
            i += 1
            continue

        # FIX 6: type confusion — use separate fields instead of union
        if "pkt->handler.process_cb" in line:
            out.append(line.replace("pkt->handler.process_cb",
                                    "pkt->process_cb"))
            i += 1
            continue
        if "pkt->handler.packet_type" in line:
            out.append(line.replace("pkt->handler.packet_type",
                                    "pkt->packet_type"))
            i += 1
            continue

        # FIX 7: OOB bounds check in handle_read_config
        if "config_entry_t *target = &g_config.entries[req->index];" in line:
            out.append("    if (req->index >= CONFIG_MAX_ENTRIES) {")
            out.append('        fprintf(stderr, '
                       '"[config] index %u out of bounds\\n", req->index);')
            out.append("        return -1;")
            out.append("    }")
            out.append(line)
            i += 1
            continue

        out.append(line)
        i += 1

    return "\n".join(out)


def patch_handlers_h(src):
    """Replace the union in packet_object_t with separate fields."""
    return src.replace(
        "    union {\n"
        "        uint32_t packet_type;\n"
        "        void   (*process_cb)(void *, size_t);\n"
        "    } handler;",
        "    uint32_t packet_type;\n"
        "    void   (*process_cb)(void *, size_t);",
    )


# ------------------------------------------------------------------ #
#  Defense assessment — evaluate severity and defense effectiveness   #
# ------------------------------------------------------------------ #

def make_defense_assessment(vulns):
    # Build severity ranking ordered highest-first
    ranked = sorted(vulns, key=lambda v: v["severity_score"], reverse=True)

    severity_ranking = []
    exploitability_map = {
        "VULN-001": "moderate",   # heap overflow — needs sized payload
        "VULN-002": "moderate",   # stack overflow — need to craft log event
        "VULN-003": "complex",    # UAF — need 3-step command sequence
        "VULN-004": "complex",    # double-free — need txn begin + rollback
        "VULN-005": "moderate",   # int overflow — craft count*size to wrap
        "VULN-006": "trivial",    # type confusion — single packet w/ flag
        "VULN-007": "trivial",    # OOB — single read command w/ bad index
    }

    justification_map = {
        "VULN-001": (
            "Heap buffer overflow allows arbitrary write to adjacent heap metadata "
            "or heap objects. Requires crafting a payload larger than the 128-byte "
            "buffer but no special privileges. Impact is arbitrary write primitive "
            "that can corrupt heap state for further exploitation."
        ),
        "VULN-002": (
            "Stack buffer overflow enables overwriting the return address on the "
            "stack, providing direct code execution. The validation uses the wrong "
            "constant (256 vs 64), making exploitation straightforward once the "
            "mismatch is identified. Highest impact as it directly yields RIP control."
        ),
        "VULN-003": (
            "Use-after-free on the stats structure allows reading stale or "
            "reallocated heap data. Requires a 3-command sequence (create, reset, "
            "stats) making it moderately complex. The dangling pointer reads "
            "whatever data occupies the freed region, enabling info leaks."
        ),
        "VULN-004": (
            "Double-free corrupts heap allocator metadata, potentially allowing "
            "overlapping allocations and arbitrary write. Requires understanding "
            "the rollback/callback interaction. Impact depends on heap layout "
            "but can escalate to arbitrary write via heap grooming."
        ),
        "VULN-005": (
            "Integer overflow in count*item_size wraps the allocation size to a "
            "small value while the subsequent memcpy uses the unwrapped payload "
            "length, causing a massive heap overflow. Moderate complexity as the "
            "attacker must compute wrapping values."
        ),
        "VULN-006": (
            "Type confusion via union sharing between function pointer and integer "
            "allows directly controlling the function pointer value. Trivial to "
            "exploit: set the custom-handler flag, supply a crafted packet_type, "
            "and the corrupted pointer is called immediately. Direct code execution."
        ),
        "VULN-007": (
            "Out-of-bounds array access allows reading or writing beyond the "
            "config entries array. Trivial to trigger by supplying an index >= 16. "
            "Impact is limited to adjacent stack/global data but useful for "
            "information disclosure in exploit chains."
        ),
    }

    for v in ranked:
        vid = v["id"]
        severity_ranking.append({
            "vuln_id": vid,
            "severity_score": v["severity_score"],
            "exploitability": exploitability_map.get(vid, "moderate"),
            "justification": justification_map.get(vid, ""),
        })

    # Exploit chains — multi-vulnerability combinations
    exploit_chains = [
        {
            "chain_id": "CHAIN-001",
            "vulnerabilities": ["VULN-007", "VULN-006"],
            "description": (
                "OOB read (VULN-007) leaks adjacent memory to disclose heap "
                "layout and function pointer addresses, defeating ASLR. The "
                "leaked addresses are then used to craft a valid function pointer "
                "value for the type confusion (VULN-006), achieving reliable "
                "code execution rather than a speculative crash."
            ),
            "escalated_impact": (
                "Individually, OOB gives info-leak and type confusion gives "
                "unreliable code execution (needs a valid address). Chained, "
                "they provide reliable arbitrary code execution with ASLR bypass."
            ),
        },
        {
            "chain_id": "CHAIN-002",
            "vulnerabilities": ["VULN-005", "VULN-001"],
            "description": (
                "Integer overflow (VULN-005) causes a small allocation for what "
                "should be a large batch, then the heap overflow from CMD_STORE_DATA "
                "(VULN-001) corrupts the adjacent undersized batch buffer's metadata. "
                "This provides a controlled heap corruption primitive where the "
                "attacker controls both the overflow source and the target."
            ),
            "escalated_impact": (
                "Each overflow individually corrupts unpredictable adjacent data. "
                "Combined via heap grooming, the attacker controls allocation "
                "adjacency to achieve a deterministic arbitrary write primitive."
            ),
        },
        {
            "chain_id": "CHAIN-003",
            "vulnerabilities": ["VULN-003", "VULN-004"],
            "description": (
                "The UAF (VULN-003) frees the stats structure, then the "
                "double-free (VULN-004) frees the transaction data buffer twice. "
                "After the double-free corrupts the free list, a new allocation "
                "via session create reuses the corrupted slot, placing attacker-"
                "controlled data where the stats pointer points. The subsequent "
                "stats read dereferences attacker-controlled memory."
            ),
            "escalated_impact": (
                "UAF alone reads stale data; double-free alone corrupts metadata. "
                "Chained, the attacker gets a controlled read primitive — the "
                "stats dereference reads from attacker-specified memory."
            ),
        },
    ]

    # Defense mapping — evaluate allocator vs patches
    defense_mapping = {
        "VULN-001": {
            "mechanism": "both",
            "rationale": (
                "The hardened allocator's trailing canary detects the heap overflow "
                "when the corrupted buffer is freed, providing detection. However, "
                "the individual bounds check patch prevents the overflow from "
                "occurring at all, which is the primary defense."
            ),
        },
        "VULN-002": {
            "mechanism": "patch",
            "rationale": (
                "Stack buffer overflow occurs in a stack-allocated char array, "
                "not a pool allocation. The hardened pool allocator has no "
                "visibility into stack memory. Only the individual patch (fixing "
                "the validation constant from MAX_LOG_PREFIX to LOG_ENTRY_BUFFER) "
                "addresses this vulnerability."
            ),
        },
        "VULN-003": {
            "mechanism": "both",
            "rationale": (
                "The hardened allocator's quarantine delays memory reuse, making "
                "UAF exploitation harder (freed memory is poisoned and not "
                "reallocated immediately). The individual patch nullifies the "
                "stats pointer after free, preventing the dereference entirely. "
                "Both layers provide defense-in-depth."
            ),
        },
        "VULN-004": {
            "mechanism": "both",
            "rationale": (
                "The hardened allocator detects the double-free by checking "
                "quarantine membership and refuses the second free. The "
                "individual patch nullifies data_buf before invoking the "
                "cleanup callback, preventing the callback from attempting "
                "the second free."
            ),
        },
        "VULN-005": {
            "mechanism": "patch",
            "rationale": (
                "The integer overflow occurs in arithmetic before the allocation "
                "call. The hardened allocator receives the already-wrapped size "
                "and cannot detect that it was supposed to be larger. Only the "
                "individual overflow guard (checking count > UINT32_MAX / "
                "item_size) prevents the vulnerability."
            ),
        },
        "VULN-006": {
            "mechanism": "patch",
            "rationale": (
                "Type confusion is a logic/design bug in the packet_object_t "
                "union where a function pointer and integer share storage. The "
                "pool allocator manages the allocation but cannot enforce type "
                "safety within the allocated structure. Only the structural fix "
                "(separating the union into distinct fields) resolves this."
            ),
        },
        "VULN-007": {
            "mechanism": "patch",
            "rationale": (
                "Out-of-bounds array indexing into a global config_store_t "
                "structure uses a static array, not a pool allocation. The "
                "hardened allocator has no control over static array accesses. "
                "Only the individual bounds check (index < CONFIG_MAX_ENTRIES) "
                "prevents this."
            ),
        },
    }

    return {
        "severity_ranking": severity_ranking,
        "exploit_chains": exploit_chains,
        "defense_mapping": defense_mapping,
    }


# ------------------------------------------------------------------ #
#  Main                                                               #
# ------------------------------------------------------------------ #

def main():
    handlers_src = read_file(os.path.join(SRC_DIR, "handlers.c"))
    headers_src  = read_file(os.path.join(SRC_DIR, "handlers.h"))

    # --- 1. Analyse ---
    print("Analysing source code...")
    vulns = analyze(handlers_src, headers_src)
    for v in vulns:
        print(f"  {v['id']}: {v['type']} in {v['function']} "
              f"({v['cwe']}, severity={v['severity_score']})")

    report = {"vulnerabilities": vulns}
    write_file(REPORT, json.dumps(report, indent=2) + "\n")
    print(f"\nWrote {len(vulns)} findings to {REPORT}")

    # --- 2. Create hardened pool allocator ---
    print("\nCreating hardened pool allocator...")
    os.makedirs(HARDEN_DIR, exist_ok=True)
    write_file(os.path.join(HARDEN_DIR, "pool.h"), HARDENED_POOL_H)
    write_file(os.path.join(HARDEN_DIR, "pool.c"), HARDENED_POOL_C)
    print(f"  Written to {HARDEN_DIR}/")

    # --- 3. Generate patched source ---
    print("\nGenerating patched source with hardened allocator...")
    os.makedirs(f"{PATCH_DIR}/src", exist_ok=True)

    # Copy hardened allocator as drop-in replacement for pool.c/pool.h
    write_file(os.path.join(PATCH_DIR, "src", "pool.h"), HARDENED_POOL_H)
    write_file(os.path.join(PATCH_DIR, "src", "pool.c"), HARDENED_POOL_C)

    # Copy unchanged files
    for f in ("protocol.h", "vdriver.c"):
        shutil.copy2(os.path.join(SRC_DIR, f),
                     os.path.join(PATCH_DIR, "src", f))
    shutil.copy2("/app/Makefile", os.path.join(PATCH_DIR, "Makefile"))

    # Patch handlers.h (fix union -> separate fields)
    write_file(os.path.join(PATCH_DIR, "src", "handlers.h"),
               patch_handlers_h(headers_src))

    # Patch handlers.c (fix all 7 vulnerabilities)
    write_file(os.path.join(PATCH_DIR, "src", "handlers.c"),
               patch_handlers(handlers_src))

    # Verify build
    print("Compiling patched code...")
    r = subprocess.run(["make", "asan"], cwd=PATCH_DIR, capture_output=True)
    if r.returncode == 0:
        print("  Patched code compiles successfully.")
    else:
        print(f"  ERROR: compile failed:\n{r.stderr.decode()}")

    # --- 4. Generate defense assessment ---
    print("\nGenerating defense assessment...")
    assessment = make_defense_assessment(vulns)
    write_file(ASSESS, json.dumps(assessment, indent=2) + "\n")
    print(f"  Written to {ASSESS}")
    print(f"  Severity ranking: {[e['vuln_id'] for e in assessment['severity_ranking']]}")
    print(f"  Exploit chains: {len(assessment['exploit_chains'])}")
    print(f"  Defense mappings: {len(assessment['defense_mapping'])}")

    print("\nDone.")


if __name__ == "__main__":
    main()
