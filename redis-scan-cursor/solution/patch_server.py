#!/usr/bin/env python3
"""Patch server.cpp to add the SCAN command with reverse-bit cursor iteration."""

import re

SERVER = "/app/server.cpp"

with open(SERVER, "r") as f:
    code = f.read()

# ── 1. Insert helper functions before do_request ─────────────────────────────

SCAN_IMPL = r'''
// ── SCAN helpers ────────────────────────────────────────────────────────────

// Reverse all 64 bits of v.
static uint64_t rev64(uint64_t v) {
    v = ((v >> 1)  & 0x5555555555555555ULL) | ((v & 0x5555555555555555ULL) << 1);
    v = ((v >> 2)  & 0x3333333333333333ULL) | ((v & 0x3333333333333333ULL) << 2);
    v = ((v >> 4)  & 0x0F0F0F0F0F0F0F0FULL) | ((v & 0x0F0F0F0F0F0F0F0FULL) << 4);
    v = ((v >> 8)  & 0x00FF00FF00FF00FFULL) | ((v & 0x00FF00FF00FF00FFULL) << 8);
    v = ((v >> 16) & 0x0000FFFF0000FFFFULL) | ((v & 0x0000FFFF0000FFFFULL) << 16);
    v = (v >> 32) | (v << 32);
    return v;
}

static bool str2uint(const std::string &s, uint64_t &out) {
    char *endp = NULL;
    out = strtoull(s.c_str(), &endp, 10);
    return endp == s.c_str() + s.size();
}

// Collect keys from a single hash-chain into `keys`.
static void scan_emit_slot(HNode *head, std::vector<std::string> &keys) {
    for (HNode *node = head; node; node = node->next) {
        Entry *ent = container_of(node, Entry, node);
        keys.push_back(ent->key);
    }
}

// scan cursor [count n]
static void do_scan(std::vector<std::string> &cmd, Buffer &out) {
    // ── parse arguments ──
    uint64_t cursor = 0;
    if (!str2uint(cmd[1], cursor)) {
        return out_err(out, ERR_BAD_ARG, "expect uint64");
    }

    int64_t count = 10;
    if (cmd.size() == 4) {
        if (cmd[2] != "count") {
            return out_err(out, ERR_BAD_ARG, "expect 'count'");
        }
        if (!str2int(cmd[3], count) || count < 1) {
            return out_err(out, ERR_BAD_ARG, "expect positive int");
        }
    }

    // ── handle empty database ──
    HTab *t0 = &g_data.db.newer;
    HTab *t1 = &g_data.db.older;

    if (!t0->tab && !t1->tab) {
        out_arr(out, 2);
        out_int(out, 0);
        out_arr(out, 0);
        return;
    }

    // ensure t0 is the *smaller* table (fewer slots)
    if (t1->tab && (!t0->tab || t0->mask > t1->mask)) {
        HTab *tmp = t0; t0 = t1; t1 = tmp;
    }

    // ── iterate using reverse-bit cursor ──
    std::vector<std::string> keys;

    while ((int64_t)keys.size() < count) {
        if (t1->tab) {
            // Two tables — rehashing in progress.
            // Visit the matching slot in the smaller table …
            size_t m0 = t0->mask;
            size_t m1 = t1->mask;

            scan_emit_slot(t0->tab[cursor & m0], keys);

            // … then visit ALL corresponding slots in the larger table.
            uint64_t v = cursor;
            do {
                scan_emit_slot(t1->tab[v & m1], keys);
                v |= ~m1;
                v = rev64(v);
                v++;
                v = rev64(v);
            } while (v & (m0 ^ m1));

            cursor = v;
        } else {
            // Single table — straightforward.
            size_t m0 = t0->mask;

            scan_emit_slot(t0->tab[cursor & m0], keys);

            cursor |= ~m0;
            cursor = rev64(cursor);
            cursor++;
            cursor = rev64(cursor);
        }

        if (cursor == 0) {
            break;  // full cycle complete
        }
    }

    // ── serialise response: [cursor, [key, …]] ──
    out_arr(out, 2);
    out_int(out, (int64_t)cursor);
    out_arr(out, (uint32_t)keys.size());
    for (const auto &k : keys) {
        out_str(out, k.data(), k.size());
    }
}

'''

# Insert just before do_request
ANCHOR = "static void do_request(std::vector<std::string> &cmd, Buffer &out) {"
assert ANCHOR in code, "cannot find do_request in server.cpp"
code = code.replace(ANCHOR, SCAN_IMPL + ANCHOR)

# ── 2. Add scan dispatch inside do_request ───────────────────────────────────

OLD_DISPATCH = '    } else {\n        return out_err(out, ERR_UNKNOWN, "unknown command.");'
NEW_DISPATCH = (
    '    } else if ((cmd.size() == 2 || cmd.size() == 4) && cmd[0] == "scan") {\n'
    '        return do_scan(cmd, out);\n'
    '    } else {\n'
    '        return out_err(out, ERR_UNKNOWN, "unknown command.");'
)
assert OLD_DISPATCH in code, "cannot find unknown-command dispatch in server.cpp"
code = code.replace(OLD_DISPATCH, NEW_DISPATCH)

with open(SERVER, "w") as f:
    f.write(code)

print("server.cpp patched with SCAN command")
