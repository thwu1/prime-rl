/* ===================================================================
 * Persistent set operations: union, intersection, difference
 * ===================================================================
 */

/* --- Helper struct for optional node results --- */
struct setop_result {
    struct hamt_node node;
    bool present;
};

/* Get the 5-bit hash index for a key at a given trie depth.
 * The HAMT uses 5 bits per level from a 32-bit hash. Every 6 levels
 * (30 bits consumed), a new hash is generated using the depth as seed. */
static uint32_t setop_hash_at_depth(hamt_key_hash_fn fn, const void *key,
                                    size_t depth)
{
    size_t gen = (depth / 6) * 6;
    size_t shift = (depth % 6) * 5;
    return (fn(key, gen) >> shift) & 0x1f;
}

/* Count all leaf nodes in a subtree rooted at node */
static size_t setop_count_leaves(const struct hamt_node *node)
{
    if (is_value(node->as.kv.value))
        return 1;
    size_t count = 0;
    int nr = get_popcount(INDEX(node));
    for (int i = 0; i < nr; i++)
        count += setop_count_leaves(&TABLE(node)[i]);
    return count;
}

/* ======== Forward declarations ======== */
static struct hamt_node setop_u_merge(struct hamt *h, struct hamt_node *a1,
    struct hamt_node *a2, hamt_conflict_fn cf, size_t d, size_t *nc);
static struct hamt_node setop_u_children(struct hamt *h, struct hamt_node *c1,
    struct hamt_node *c2, hamt_conflict_fn cf, size_t d, size_t *nc);
static struct hamt_node setop_u_build(struct hamt *h, struct hamt_node *l1,
    struct hamt_node *l2, size_t d);
static struct hamt_node setop_u_insert(struct hamt *h, struct hamt_node *internal,
    void *key, void *vtag, hamt_conflict_fn cf, bool leaf_is_first,
    size_t d, size_t *nc);

static struct setop_result setop_i_merge(struct hamt *h, struct hamt_node *a1,
    struct hamt_node *a2, hamt_conflict_fn cf, size_t d);
static struct setop_result setop_i_children(struct hamt *h, struct hamt_node *c1,
    struct hamt_node *c2, hamt_conflict_fn cf, size_t d);
static struct setop_result setop_i_find(struct hamt *h, struct hamt_node *internal,
    void *key, void *vtag, hamt_conflict_fn cf, bool key_is_first, size_t d);

static struct setop_result setop_d_merge(struct hamt *h, struct hamt_node *a1,
    struct hamt_node *a2, size_t d);
static struct setop_result setop_d_children(struct hamt *h, struct hamt_node *c1,
    struct hamt_node *c2, size_t d);
static bool setop_d_exists(const struct hamt *h, struct hamt_node *internal,
    const void *key, size_t d);
static struct setop_result setop_d_remove_key(struct hamt *h,
    struct hamt_node *internal, const void *key, size_t d);

/* ======== UNION helpers ======== */

/* Build a subtrie containing two leaf nodes with different keys.
 * NOTE: macros TABLE/INDEX/KEY/VALUE don't parenthesize their arg,
 * so we must never pass &struct_var — use a pointer variable instead. */
static struct hamt_node setop_u_build(struct hamt *h, struct hamt_node *l1,
    struct hamt_node *l2, size_t d)
{
    struct hamt_node r;
    struct hamt_node *rp = &r;
    uint32_t i1 = setop_hash_at_depth(h->key_hash, KEY(l1), d);
    uint32_t i2 = setop_hash_at_depth(h->key_hash, KEY(l2), d);
    if (i1 != i2) {
        uint32_t bm = (1 << i1) | (1 << i2);
        TABLE(rp) = table_allocate(h, 2);
        INDEX(rp) = bm;
        TABLE(rp)[get_pos(i1, bm)] = *l1;
        TABLE(rp)[get_pos(i2, bm)] = *l2;
    } else {
        TABLE(rp) = table_allocate(h, 1);
        INDEX(rp) = (1 << i1);
        TABLE(rp)[0] = setop_u_build(h, l1, l2, d + 1);
    }
    return r;
}

/* Insert a leaf into an internal node's subtree, creating new nodes.
 * leaf_is_first: true if the leaf is from t1 (for conflict ordering). */
static struct hamt_node setop_u_insert(struct hamt *h,
    struct hamt_node *internal, void *key, void *vtag,
    hamt_conflict_fn cf, bool leaf_is_first, size_t d, size_t *nc)
{
    struct hamt_node r;
    struct hamt_node *rp = &r;
    uint32_t ix = setop_hash_at_depth(h->key_hash, key, d);
    uint32_t bm = INDEX(internal);
    int nr = get_popcount(bm);

    if (bm & (1 << ix)) {
        int pos = get_pos(ix, bm);
        struct hamt_node *ch = &TABLE(internal)[pos];
        /* Duplicate table */
        TABLE(rp) = table_allocate(h, nr);
        INDEX(rp) = bm;
        memcpy(TABLE(rp), TABLE(internal), nr * sizeof(struct hamt_node));

        if (is_value(VALUE(ch))) {
            if (h->key_cmp(key, KEY(ch)) == 0) {
                /* Same key: conflict resolution */
                void *v1, *v2;
                if (leaf_is_first) {
                    v1 = untagged(vtag);
                    v2 = untagged(VALUE(ch));
                } else {
                    v1 = untagged(VALUE(ch));
                    v2 = untagged(vtag);
                }
                void *m = cf(key, v1, v2);
                struct hamt_node *slot = &TABLE(rp)[pos];
                KEY(slot) = key;
                VALUE(slot) = tagged(m);
                *nc += 1;
            } else {
                /* Different key: build subtrie */
                struct hamt_node ex = *ch;
                struct hamt_node nl;
                struct hamt_node *nlp = &nl;
                KEY(nlp) = key;
                VALUE(nlp) = vtag;
                TABLE(rp)[pos] = setop_u_build(h, &ex, &nl, d + 1);
            }
        } else {
            /* Internal child: recurse */
            TABLE(rp)[pos] = setop_u_insert(h, ch, key, vtag, cf,
                                            leaf_is_first, d + 1, nc);
        }
    } else {
        /* Slot empty: extend table */
        uint32_t nbm = bm | (1 << ix);
        int np = get_pos(ix, nbm);
        TABLE(rp) = table_allocate(h, nr + 1);
        INDEX(rp) = nbm;
        memcpy(&TABLE(rp)[0], &TABLE(internal)[0],
               np * sizeof(struct hamt_node));
        struct hamt_node *slot = &TABLE(rp)[np];
        KEY(slot) = key;
        VALUE(slot) = vtag;
        memcpy(&TABLE(rp)[np + 1], &TABLE(internal)[np],
               (nr - np) * sizeof(struct hamt_node));
    }
    return r;
}

/* Merge two child nodes (each can be leaf or internal) */
static struct hamt_node setop_u_children(struct hamt *h,
    struct hamt_node *c1, struct hamt_node *c2,
    hamt_conflict_fn cf, size_t d, size_t *nc)
{
    bool l1 = is_value(VALUE(c1));
    bool l2 = is_value(VALUE(c2));

    if (l1 && l2) {
        if (h->key_cmp(KEY(c1), KEY(c2)) == 0) {
            /* Same key: conflict resolution (t1 value first) */
            struct hamt_node rn;
            struct hamt_node *rnp = &rn;
            void *m = cf(KEY(c1), untagged(VALUE(c1)), untagged(VALUE(c2)));
            KEY(rnp) = KEY(c1);
            VALUE(rnp) = tagged(m);
            *nc += 1;
            return rn;
        }
        return setop_u_build(h, c1, c2, d);
    } else if (l1) {
        /* c1 is leaf (t1), c2 is internal (t2): insert c1 into c2 */
        return setop_u_insert(h, c2, KEY(c1), VALUE(c1), cf, true, d, nc);
    } else if (l2) {
        /* c1 is internal (t1), c2 is leaf (t2): insert c2 into c1 */
        return setop_u_insert(h, c1, KEY(c2), VALUE(c2), cf, false, d, nc);
    } else {
        /* Both internal: recurse */
        return setop_u_merge(h, c1, c2, cf, d, nc);
    }
}

/* Merge two internal nodes */
static struct hamt_node setop_u_merge(struct hamt *h,
    struct hamt_node *a1, struct hamt_node *a2,
    hamt_conflict_fn cf, size_t d, size_t *nc)
{
    struct hamt_node r;
    struct hamt_node *rp = &r;
    uint32_t b1 = INDEX(a1), b2 = INDEX(a2);
    uint32_t combined = b1 | b2;
    int n = get_popcount(combined);
    TABLE(rp) = table_allocate(h, n);
    INDEX(rp) = combined;

    for (int bit = 0; bit < 32; bit++) {
        if (!(combined & (1 << bit)))
            continue;
        int pos = get_pos(bit, combined);
        bool in1 = (b1 & (1 << bit)) != 0;
        bool in2 = (b2 & (1 << bit)) != 0;

        if (in1 && !in2) {
            TABLE(rp)[pos] = TABLE(a1)[get_pos(bit, b1)];
        } else if (!in1 && in2) {
            TABLE(rp)[pos] = TABLE(a2)[get_pos(bit, b2)];
        } else {
            TABLE(rp)[pos] = setop_u_children(h,
                &TABLE(a1)[get_pos(bit, b1)],
                &TABLE(a2)[get_pos(bit, b2)],
                cf, d + 1, nc);
        }
    }
    return r;
}

/* ======== Public: persistent union ======== */

const struct hamt *hamt_punion(const struct hamt *t1, const struct hamt *t2,
                               hamt_conflict_fn on_conflict)
{
    struct hamt *r = ALLOC(t1->ator, sizeof(struct hamt));
    r->ator = t1->ator;
    r->key_hash = t1->key_hash;
    r->key_cmp = t1->key_cmp;
#if defined(WITH_TABLE_CACHE)
    r->cache = t1->cache;
#endif
    r->root = ALLOC(r->ator, sizeof(struct hamt_node));

    if (t1->size == 0 && t2->size == 0) {
        memset(r->root, 0, sizeof(struct hamt_node));
        r->size = 0;
    } else if (t1->size == 0) {
        *r->root = *t2->root;
        r->size = t2->size;
    } else if (t2->size == 0) {
        *r->root = *t1->root;
        r->size = t1->size;
    } else {
        size_t nc = 0;
        *r->root = setop_u_merge(r, t1->root, t2->root, on_conflict, 0, &nc);
        r->size = t1->size + t2->size - nc;
    }
    return r;
}

/* ======== INTERSECTION helpers ======== */

/* Check if a leaf key exists in an internal node's subtree.
 * If found, return the leaf with conflict-resolved value.
 * key_is_first: true if the search key is from t1. */
static struct setop_result setop_i_find(struct hamt *h,
    struct hamt_node *internal, void *key, void *vtag,
    hamt_conflict_fn cf, bool key_is_first, size_t d)
{
    uint32_t ix = setop_hash_at_depth(h->key_hash, key, d);
    uint32_t bm = INDEX(internal);
    if (!(bm & (1 << ix)))
        return (struct setop_result){.present = false};

    int pos = get_pos(ix, bm);
    struct hamt_node *ch = &TABLE(internal)[pos];

    if (is_value(VALUE(ch))) {
        if (h->key_cmp(key, KEY(ch)) == 0) {
            void *v1, *v2;
            if (key_is_first) {
                v1 = untagged(vtag);
                v2 = untagged(VALUE(ch));
            } else {
                v1 = untagged(VALUE(ch));
                v2 = untagged(vtag);
            }
            struct hamt_node rn;
            struct hamt_node *rnp = &rn;
            KEY(rnp) = key;
            VALUE(rnp) = tagged(cf(key, v1, v2));
            return (struct setop_result){.node = rn, .present = true};
        }
        return (struct setop_result){.present = false};
    }
    return setop_i_find(h, ch, key, vtag, cf, key_is_first, d + 1);
}

/* Intersect two child nodes */
static struct setop_result setop_i_children(struct hamt *h,
    struct hamt_node *c1, struct hamt_node *c2,
    hamt_conflict_fn cf, size_t d)
{
    bool l1 = is_value(VALUE(c1));
    bool l2 = is_value(VALUE(c2));

    if (l1 && l2) {
        if (h->key_cmp(KEY(c1), KEY(c2)) == 0) {
            struct hamt_node rn;
            struct hamt_node *rnp = &rn;
            KEY(rnp) = KEY(c1);
            VALUE(rnp) = tagged(cf(KEY(c1), untagged(VALUE(c1)),
                                   untagged(VALUE(c2))));
            return (struct setop_result){.node = rn, .present = true};
        }
        return (struct setop_result){.present = false};
    } else if (l1) {
        /* c1 leaf (t1), c2 internal (t2): find c1's key in c2 */
        return setop_i_find(h, c2, KEY(c1), VALUE(c1), cf, true, d);
    } else if (l2) {
        /* c1 internal (t1), c2 leaf (t2): find c2's key in c1 */
        return setop_i_find(h, c1, KEY(c2), VALUE(c2), cf, false, d);
    } else {
        return setop_i_merge(h, c1, c2, cf, d);
    }
}

/* Intersect two internal nodes */
static struct setop_result setop_i_merge(struct hamt *h,
    struct hamt_node *a1, struct hamt_node *a2,
    hamt_conflict_fn cf, size_t d)
{
    uint32_t b1 = INDEX(a1), b2 = INDEX(a2);
    uint32_t common = b1 & b2;
    if (common == 0)
        return (struct setop_result){.present = false};

    struct setop_result results[32];
    int bits[32];
    int ri = 0;

    for (int bit = 0; bit < 32; bit++) {
        if (!(common & (1 << bit)))
            continue;
        bits[ri] = bit;
        results[ri] = setop_i_children(h,
            &TABLE(a1)[get_pos(bit, b1)],
            &TABLE(a2)[get_pos(bit, b2)],
            cf, d + 1);
        ri++;
    }

    /* Build result bitmap from present children */
    uint32_t rbm = 0;
    int np = 0;
    for (int i = 0; i < ri; i++) {
        if (results[i].present) {
            rbm |= (1 << bits[i]);
            np++;
        }
    }
    if (np == 0)
        return (struct setop_result){.present = false};

    struct hamt_node r;
    struct hamt_node *rp = &r;
    TABLE(rp) = table_allocate(h, np);
    INDEX(rp) = rbm;
    int p = 0;
    for (int i = 0; i < ri; i++) {
        if (results[i].present)
            TABLE(rp)[p++] = results[i].node;
    }

    return (struct setop_result){.node = r, .present = true};
}

/* ======== Public: persistent intersection ======== */

const struct hamt *hamt_pintersection(const struct hamt *t1, const struct hamt *t2,
                                      hamt_conflict_fn on_conflict)
{
    struct hamt *r = ALLOC(t1->ator, sizeof(struct hamt));
    r->ator = t1->ator;
    r->key_hash = t1->key_hash;
    r->key_cmp = t1->key_cmp;
#if defined(WITH_TABLE_CACHE)
    r->cache = t1->cache;
#endif
    r->root = ALLOC(r->ator, sizeof(struct hamt_node));

    if (t1->size == 0 || t2->size == 0) {
        memset(r->root, 0, sizeof(struct hamt_node));
        r->size = 0;
        return r;
    }

    struct setop_result sr = setop_i_merge(r, t1->root, t2->root,
                                           on_conflict, 0);
    if (sr.present) {
        *r->root = sr.node;
        /* Count leaves in result for accurate size */
        r->size = setop_count_leaves(r->root);
    } else {
        memset(r->root, 0, sizeof(struct hamt_node));
        r->size = 0;
    }
    return r;
}

/* ======== DIFFERENCE helpers ======== */

/* Check if a key exists in an internal node's subtree */
static bool setop_d_exists(const struct hamt *h, struct hamt_node *internal,
    const void *key, size_t d)
{
    uint32_t ix = setop_hash_at_depth(h->key_hash, key, d);
    uint32_t bm = INDEX(internal);
    if (!(bm & (1 << ix)))
        return false;
    int pos = get_pos(ix, bm);
    struct hamt_node *ch = &TABLE(internal)[pos];
    if (is_value(VALUE(ch)))
        return h->key_cmp(key, KEY(ch)) == 0;
    return setop_d_exists(h, ch, key, d + 1);
}

/* Remove a single key from an internal node's subtree (creating new nodes).
 * Returns the modified subtree, or present=false if the subtree becomes empty. */
static struct setop_result setop_d_remove_key(struct hamt *h,
    struct hamt_node *internal, const void *key, size_t d)
{
    uint32_t ix = setop_hash_at_depth(h->key_hash, key, d);
    uint32_t bm = INDEX(internal);
    int nr = get_popcount(bm);

    if (!(bm & (1 << ix))) {
        /* Key not here: keep entire subtree */
        return (struct setop_result){.node = *internal, .present = true};
    }

    int pos = get_pos(ix, bm);
    struct hamt_node *ch = &TABLE(internal)[pos];

    if (is_value(VALUE(ch))) {
        if (h->key_cmp(key, KEY(ch)) == 0) {
            /* Found key: remove it */
            if (nr == 1)
                return (struct setop_result){.present = false};
            struct hamt_node r;
            struct hamt_node *rp = &r;
            uint32_t nbm = bm & ~(1 << ix);
            TABLE(rp) = table_allocate(h, nr - 1);
            INDEX(rp) = nbm;
            memcpy(&TABLE(rp)[0], &TABLE(internal)[0],
                   pos * sizeof(struct hamt_node));
            memcpy(&TABLE(rp)[pos], &TABLE(internal)[pos + 1],
                   (nr - pos - 1) * sizeof(struct hamt_node));
            return (struct setop_result){.node = r, .present = true};
        }
        /* Different key at this position: keep subtree */
        return (struct setop_result){.node = *internal, .present = true};
    }

    /* Internal child: recurse */
    struct setop_result cr = setop_d_remove_key(h, ch, key, d + 1);
    if (!cr.present) {
        /* Child became empty: shrink */
        if (nr == 1)
            return (struct setop_result){.present = false};
        struct hamt_node r;
        struct hamt_node *rp = &r;
        uint32_t nbm = bm & ~(1 << ix);
        TABLE(rp) = table_allocate(h, nr - 1);
        INDEX(rp) = nbm;
        memcpy(&TABLE(rp)[0], &TABLE(internal)[0],
               pos * sizeof(struct hamt_node));
        memcpy(&TABLE(rp)[pos], &TABLE(internal)[pos + 1],
               (nr - pos - 1) * sizeof(struct hamt_node));
        return (struct setop_result){.node = r, .present = true};
    }

    /* Child modified: copy table with new child */
    struct hamt_node r;
    struct hamt_node *rp = &r;
    TABLE(rp) = table_allocate(h, nr);
    INDEX(rp) = bm;
    memcpy(TABLE(rp), TABLE(internal), nr * sizeof(struct hamt_node));
    TABLE(rp)[pos] = cr.node;
    return (struct setop_result){.node = r, .present = true};
}

/* Difference two child nodes */
static struct setop_result setop_d_children(struct hamt *h,
    struct hamt_node *c1, struct hamt_node *c2, size_t d)
{
    bool l1 = is_value(VALUE(c1));
    bool l2 = is_value(VALUE(c2));

    if (l1 && l2) {
        if (h->key_cmp(KEY(c1), KEY(c2)) == 0)
            return (struct setop_result){.present = false};
        /* Different keys at same position: keep c1 */
        return (struct setop_result){.node = *c1, .present = true};
    } else if (l1) {
        /* c1 leaf, c2 internal: keep c1 only if NOT found in c2 */
        if (setop_d_exists(h, c2, KEY(c1), d))
            return (struct setop_result){.present = false};
        return (struct setop_result){.node = *c1, .present = true};
    } else if (l2) {
        /* c1 internal, c2 leaf: remove c2's key from c1's subtree */
        return setop_d_remove_key(h, c1, KEY(c2), d);
    } else {
        return setop_d_merge(h, c1, c2, d);
    }
}

/* Difference two internal nodes: keep entries from a1 not in a2 */
static struct setop_result setop_d_merge(struct hamt *h,
    struct hamt_node *a1, struct hamt_node *a2, size_t d)
{
    uint32_t b1 = INDEX(a1), b2 = INDEX(a2);
    uint32_t only1 = b1 & ~b2;
    uint32_t common = b1 & b2;

    struct setop_result results[32];
    int bits[32];
    int ri = 0;

    /* Slots only in t1: share structure */
    for (int bit = 0; bit < 32; bit++) {
        if (only1 & (1 << bit)) {
            bits[ri] = bit;
            results[ri].node = TABLE(a1)[get_pos(bit, b1)];
            results[ri].present = true;
            ri++;
        }
    }

    /* Common slots: recursively diff */
    for (int bit = 0; bit < 32; bit++) {
        if (common & (1 << bit)) {
            bits[ri] = bit;
            results[ri] = setop_d_children(h,
                &TABLE(a1)[get_pos(bit, b1)],
                &TABLE(a2)[get_pos(bit, b2)],
                d + 1);
            ri++;
        }
    }

    /* Build result bitmap */
    uint32_t rbm = 0;
    int np = 0;
    for (int i = 0; i < ri; i++) {
        if (results[i].present) {
            rbm |= (1 << bits[i]);
            np++;
        }
    }
    if (np == 0)
        return (struct setop_result){.present = false};

    struct hamt_node r;
    struct hamt_node *rp = &r;
    TABLE(rp) = table_allocate(h, np);
    INDEX(rp) = rbm;
    int p = 0;
    /* Fill table in bitmap order */
    for (int bit = 0; bit < 32; bit++) {
        if (!(rbm & (1 << bit)))
            continue;
        for (int i = 0; i < ri; i++) {
            if (bits[i] == bit && results[i].present) {
                TABLE(rp)[p++] = results[i].node;
                break;
            }
        }
    }

    return (struct setop_result){.node = r, .present = true};
}

/* ======== Public: persistent difference ======== */

const struct hamt *hamt_pdifference(const struct hamt *t1, const struct hamt *t2)
{
    struct hamt *r = ALLOC(t1->ator, sizeof(struct hamt));
    r->ator = t1->ator;
    r->key_hash = t1->key_hash;
    r->key_cmp = t1->key_cmp;
#if defined(WITH_TABLE_CACHE)
    r->cache = t1->cache;
#endif
    r->root = ALLOC(r->ator, sizeof(struct hamt_node));

    if (t1->size == 0) {
        memset(r->root, 0, sizeof(struct hamt_node));
        r->size = 0;
        return r;
    }
    if (t2->size == 0) {
        *r->root = *t1->root;
        r->size = t1->size;
        return r;
    }

    struct setop_result sr = setop_d_merge(r, t1->root, t2->root, 0);
    if (sr.present) {
        *r->root = sr.node;
        r->size = setop_count_leaves(r->root);
    } else {
        memset(r->root, 0, sizeof(struct hamt_node));
        r->size = 0;
    }
    return r;
}
