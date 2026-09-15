#!/usr/bin/env python3
"""
Patches the Redis-like server source to add ZUNIONSTORE, ZINTERSTORE,
ZREMRANGEBYSCORE, and ZRANGEBYSCORE commands.

Only server.cpp needs modification — the existing AVL tree, sorted set,
and hashtable APIs are sufficient.
"""


def patch_server_cpp():
    path = '/app/server.cpp'
    with open(path, 'r') as f:
        content = f.read()

    # 1. Add #include <unordered_map> after #include <vector>
    content = content.replace(
        '#include <vector>',
        '#include <vector>\n#include <unordered_map>',
        1
    )

    # 2. Add new handler functions before do_request
    new_handlers = r"""
// Aggregation modes for ZUNIONSTORE/ZINTERSTORE
enum { AGG_SUM = 0, AGG_MIN = 1, AGG_MAX = 2 };

// Parse optional WEIGHTS and AGGREGATE from cmd starting at position pos
static bool parse_store_options(
    std::vector<std::string> &cmd, size_t pos, int64_t numkeys,
    std::vector<double> &weights, int &agg, Buffer &out)
{
    while (pos < cmd.size()) {
        if (cmd[pos] == "weights") {
            pos++;
            for (int64_t i = 0; i < numkeys; i++) {
                if (pos >= cmd.size()) {
                    out_err(out, ERR_BAD_ARG, "not enough weights");
                    return false;
                }
                if (!str2dbl(cmd[pos], weights[(size_t)i])) {
                    out_err(out, ERR_BAD_ARG, "expect float for weight");
                    return false;
                }
                pos++;
            }
        } else if (cmd[pos] == "aggregate") {
            pos++;
            if (pos >= cmd.size()) {
                out_err(out, ERR_BAD_ARG, "expect aggregate mode");
                return false;
            }
            if (cmd[pos] == "sum") agg = AGG_SUM;
            else if (cmd[pos] == "min") agg = AGG_MIN;
            else if (cmd[pos] == "max") agg = AGG_MAX;
            else {
                out_err(out, ERR_BAD_ARG, "unknown aggregate mode");
                return false;
            }
            pos++;
        } else {
            out_err(out, ERR_BAD_ARG, "unexpected argument");
            return false;
        }
    }
    return true;
}

// Delete existing dest key (any type) and store result map as new sorted set
static void store_result(
    const std::string &dest_name,
    std::unordered_map<std::string, double> &result_map,
    Buffer &out)
{
    // Delete existing dest (any type)
    LookupKey dkey;
    dkey.key = dest_name;
    dkey.node.hcode = str_hash((uint8_t *)dkey.key.data(), dkey.key.size());
    HNode *existing = hm_delete(&g_data.db, &dkey.node, &entry_eq);
    if (existing) {
        entry_del(container_of(existing, Entry, node));
    }

    if (result_map.empty()) {
        return out_int(out, 0);
    }

    // Create new sorted set entry
    Entry *ent = entry_new(T_ZSET);
    ent->key = dest_name;
    ent->node.hcode = str_hash((uint8_t *)ent->key.data(), ent->key.size());
    hm_insert(&g_data.db, &ent->node);

    for (auto &p : result_map) {
        zset_insert(&ent->zset, p.first.data(), p.first.size(), p.second);
    }

    return out_int(out, (int64_t)result_map.size());
}

// zunionstore dest numkeys key [key ...] [weights w1 ...] [aggregate sum|min|max]
static void do_zunionstore(std::vector<std::string> &cmd, Buffer &out) {
    int64_t numkeys = 0;
    if (!str2int(cmd[2], numkeys) || numkeys < 1) {
        return out_err(out, ERR_BAD_ARG, "expect positive int for numkeys");
    }

    size_t keys_end = 3 + (size_t)numkeys;
    if (keys_end > cmd.size()) {
        return out_err(out, ERR_BAD_ARG, "not enough keys");
    }

    // Save dest name before expect_zset modifies cmd strings
    std::string dest_name = cmd[1];

    // Collect source ZSets
    std::vector<ZSet *> sources;
    for (size_t i = 3; i < keys_end; i++) {
        ZSet *zs = expect_zset(cmd[i]);
        if (!zs) {
            return out_err(out, ERR_BAD_TYP, "expect zset");
        }
        sources.push_back(zs);
    }

    // Parse optional WEIGHTS and AGGREGATE
    std::vector<double> weights((size_t)numkeys, 1.0);
    int agg = AGG_SUM;
    if (!parse_store_options(cmd, keys_end, numkeys, weights, agg, out)) {
        return;
    }

    // Build union: iterate all source sets, aggregate scores
    std::unordered_map<std::string, double> result_map;

    for (size_t si = 0; si < sources.size(); si++) {
        ZSet *zs = sources[si];
        if (!zs->root) continue;

        // Walk AVL tree from leftmost to rightmost
        AVLNode *n = zs->root;
        while (n->left) n = n->left;

        while (n) {
            ZNode *zn = container_of(n, ZNode, tree);
            std::string name(zn->name, zn->len);
            double ws = zn->score * weights[si];

            auto it = result_map.find(name);
            if (it == result_map.end()) {
                result_map[name] = ws;
            } else {
                switch (agg) {
                    case AGG_SUM: it->second += ws; break;
                    case AGG_MIN: if (ws < it->second) it->second = ws; break;
                    case AGG_MAX: if (ws > it->second) it->second = ws; break;
                }
            }

            n = avl_offset(n, +1);
        }
    }

    store_result(dest_name, result_map, out);
}

// zinterstore dest numkeys key [key ...] [weights w1 ...] [aggregate sum|min|max]
static void do_zinterstore(std::vector<std::string> &cmd, Buffer &out) {
    int64_t numkeys = 0;
    if (!str2int(cmd[2], numkeys) || numkeys < 1) {
        return out_err(out, ERR_BAD_ARG, "expect positive int for numkeys");
    }

    size_t keys_end = 3 + (size_t)numkeys;
    if (keys_end > cmd.size()) {
        return out_err(out, ERR_BAD_ARG, "not enough keys");
    }

    std::string dest_name = cmd[1];

    std::vector<ZSet *> sources;
    for (size_t i = 3; i < keys_end; i++) {
        ZSet *zs = expect_zset(cmd[i]);
        if (!zs) {
            return out_err(out, ERR_BAD_TYP, "expect zset");
        }
        sources.push_back(zs);
    }

    std::vector<double> weights((size_t)numkeys, 1.0);
    int agg = AGG_SUM;
    if (!parse_store_options(cmd, keys_end, numkeys, weights, agg, out)) {
        return;
    }

    std::unordered_map<std::string, double> result_map;

    // Find the smallest source for efficient intersection
    size_t min_idx = 0;
    size_t min_size = (size_t)-1;
    for (size_t i = 0; i < sources.size(); i++) {
        size_t sz = avl_cnt(sources[i]->root);
        if (sz < min_size) {
            min_size = sz;
            min_idx = i;
        }
    }

    if (min_size > 0) {
        // Iterate smallest set, check membership in all others
        AVLNode *n = sources[min_idx]->root;
        while (n->left) n = n->left;

        while (n) {
            ZNode *zn = container_of(n, ZNode, tree);

            bool in_all = true;
            for (size_t i = 0; i < sources.size(); i++) {
                if (i == min_idx) continue;
                if (!zset_lookup(sources[i], zn->name, zn->len)) {
                    in_all = false;
                    break;
                }
            }

            if (in_all) {
                double result_score = zn->score * weights[min_idx];
                for (size_t i = 0; i < sources.size(); i++) {
                    if (i == min_idx) continue;
                    ZNode *other = zset_lookup(sources[i], zn->name, zn->len);
                    double ws = other->score * weights[i];
                    switch (agg) {
                        case AGG_SUM: result_score += ws; break;
                        case AGG_MIN: if (ws < result_score) result_score = ws; break;
                        case AGG_MAX: if (ws > result_score) result_score = ws; break;
                    }
                }
                std::string name(zn->name, zn->len);
                result_map[name] = result_score;
            }

            n = avl_offset(n, +1);
        }
    }

    store_result(dest_name, result_map, out);
}

// zremrangebyscore key min max
static void do_zremrangebyscore(std::vector<std::string> &cmd, Buffer &out) {
    double min_score = 0, max_score = 0;
    if (!str2dbl(cmd[2], min_score) || !str2dbl(cmd[3], max_score)) {
        return out_err(out, ERR_BAD_ARG, "expect fp number");
    }

    ZSet *zset = expect_zset(cmd[1]);
    if (!zset) {
        return out_err(out, ERR_BAD_TYP, "expect zset");
    }
    if (!zset->root) {
        return out_int(out, 0);
    }

    // Collect all nodes in range [min, max] before deleting
    // (deleting during traversal would corrupt the tree)
    std::vector<ZNode *> to_delete;
    ZNode *node = zset_seekge(zset, min_score, "", 0);
    while (node && node->score <= max_score) {
        to_delete.push_back(node);
        node = znode_offset(node, +1);
    }

    // Delete collected nodes from both indices
    for (ZNode *dn : to_delete) {
        zset_delete(zset, dn);
    }

    return out_int(out, (int64_t)to_delete.size());
}

// zrangebyscore key min max [limit offset count]
static void do_zrangebyscore(std::vector<std::string> &cmd, Buffer &out) {
    double min_score = 0, max_score = 0;
    if (!str2dbl(cmd[2], min_score) || !str2dbl(cmd[3], max_score)) {
        return out_err(out, ERR_BAD_ARG, "expect fp number");
    }

    bool has_limit = false;
    int64_t lim_offset = 0, lim_count = 0;
    if (cmd.size() == 7) {
        if (cmd[4] != "limit") {
            return out_err(out, ERR_BAD_ARG, "expect 'limit'");
        }
        if (!str2int(cmd[5], lim_offset) || !str2int(cmd[6], lim_count)) {
            return out_err(out, ERR_BAD_ARG, "expect int");
        }
        has_limit = true;
    }

    ZSet *zset = expect_zset(cmd[1]);
    if (!zset) {
        return out_err(out, ERR_BAD_TYP, "expect zset");
    }
    if (!zset->root) {
        return out_arr(out, 0);
    }

    // Seek to first element with score >= min
    ZNode *node = zset_seekge(zset, min_score, "", 0);

    // Skip offset elements within the score range
    if (has_limit) {
        for (int64_t i = 0; i < lim_offset && node && node->score <= max_score; i++) {
            node = znode_offset(node, +1);
        }
    }

    // Output matching elements
    size_t ctx = out_begin_arr(out);
    uint32_t n = 0;
    int64_t emitted = 0;
    while (node && node->score <= max_score) {
        if (has_limit && lim_count >= 0 && emitted >= lim_count) break;
        out_str(out, node->name, node->len);
        out_dbl(out, node->score);
        node = znode_offset(node, +1);
        n += 2;
        emitted++;
    }
    out_end_arr(out, ctx, n);
}

"""

    # Insert new handlers before do_request
    marker = "static void do_request("
    idx = content.find(marker)
    if idx == -1:
        raise ValueError("Could not find do_request function in server.cpp")
    content = content[:idx] + new_handlers + content[idx:]

    # 3. Add new command dispatch entries
    old_dispatch = '    } else {\n        return out_err(out, ERR_UNKNOWN, "unknown command.");'
    new_dispatch = (
        '    } else if (cmd.size() >= 4 && cmd[0] == "zunionstore") {\n'
        '        return do_zunionstore(cmd, out);\n'
        '    } else if (cmd.size() >= 4 && cmd[0] == "zinterstore") {\n'
        '        return do_zinterstore(cmd, out);\n'
        '    } else if (cmd.size() == 4 && cmd[0] == "zremrangebyscore") {\n'
        '        return do_zremrangebyscore(cmd, out);\n'
        '    } else if ((cmd.size() == 4 || cmd.size() == 7) && cmd[0] == "zrangebyscore") {\n'
        '        return do_zrangebyscore(cmd, out);\n'
        '    } else {\n'
        '        return out_err(out, ERR_UNKNOWN, "unknown command.");'
    )
    content = content.replace(old_dispatch, new_dispatch, 1)

    with open(path, 'w') as f:
        f.write(content)
    print(f"  Patched {path}")


if __name__ == '__main__':
    print("Applying solution patches...")
    patch_server_cpp()
    print("All patches applied successfully.")
