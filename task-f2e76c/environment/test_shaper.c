/*
 * test_shaper.c — Test harness for libnetshaper
 *
 * Each test case is a self-contained function that returns 0 on PASS,
 * 1 on FAIL.  The binary accepts a test name (or "all") on the command
 * line.
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "shaper.h"

#define TEST_PASS() do { printf("PASS\n"); return 0; } while (0)

#define ASSERT_EQ(a, b, msg)                                            \
	do {                                                            \
		long _a = (long)(a), _b = (long)(b);                    \
		if (_a != _b) {                                         \
			printf("FAIL: %s (got %ld, expected %ld)\n",    \
			       (msg), _a, _b);                          \
			return 1;                                       \
		}                                                       \
	} while (0)

#define ASSERT_NE(a, b, msg)                                            \
	do {                                                            \
		if ((long)(a) == (long)(b)) {                            \
			printf("FAIL: %s\n", (msg));                    \
			return 1;                                       \
		}                                                       \
	} while (0)

#define ASSERT_TRUE(x, msg)                                             \
	do {                                                            \
		if (!(x)) {                                             \
			printf("FAIL: %s\n", (msg));                    \
			return 1;                                       \
		}                                                       \
	} while (0)

/* ================================================================== */
/*  Handle validation tests                                            */
/* ================================================================== */

/*
 * QUEUE scope handles always designate a specific hardware queue.
 * An id of SHAPER_HANDLE_ID_UNSET means "no queue specified" and must
 * be rejected.
 */
static int test_handle_queue_no_id(void)
{
	struct shaper_handle h = {
		.scope = SHAPER_SCOPE_QUEUE,
		.id    = SHAPER_HANDLE_ID_UNSET,
	};

	int ret = shaper_handle_validate(&h);
	ASSERT_NE(ret, 0, "QUEUE scope with UNSET id must be rejected");

	/* A valid queue id should be accepted */
	h.id = 7;
	ret = shaper_handle_validate(&h);
	ASSERT_EQ(ret, 0, "QUEUE scope with valid id should succeed");

	TEST_PASS();
}

/*
 * NETDEV scope is a per-device singleton — only id 0 is valid.
 */
static int test_handle_netdev_nonzero_id(void)
{
	struct shaper_handle h = {
		.scope = SHAPER_SCOPE_NETDEV,
		.id    = 42,
	};

	int ret = shaper_handle_validate(&h);
	ASSERT_NE(ret, 0, "NETDEV scope with non-zero id must be rejected");

	h.id = 0;
	ret = shaper_handle_validate(&h);
	ASSERT_EQ(ret, 0, "NETDEV scope with id=0 should succeed");

	TEST_PASS();
}

/*
 * Handle ids are packed into a SHAPER_HANDLE_ID_BITS-wide field in
 * serialised formats.  Ids >= 2^SHAPER_HANDLE_ID_BITS must be rejected
 * to prevent silent truncation.
 */
static int test_handle_id_overflow(void)
{
	struct shaper_handle h = {
		.scope = SHAPER_SCOPE_QUEUE,
		.id    = (1u << SHAPER_HANDLE_ID_BITS), /* 65536 */
	};

	int ret = shaper_handle_validate(&h);
	ASSERT_NE(ret, 0,
		  "Handle id exceeding bit-width must be rejected");

	/* Maximum valid id should be accepted */
	h.id = (1u << SHAPER_HANDLE_ID_BITS) - 1; /* 65535 */
	ret = shaper_handle_validate(&h);
	ASSERT_EQ(ret, 0,
		  "Handle id at max bit-width should be accepted");

	TEST_PASS();
}

/* ================================================================== */
/*  Node active-flag test                                              */
/* ================================================================== */

/*
 * shaper_node_is_active() must return true for occupied slots and
 * false for empty/deleted ones.
 */
static int test_node_active_polarity(void)
{
	struct shaper_ctx ctx;
	struct shaper_handle h = { .scope = SHAPER_SCOPE_NODE, .id = 0 };

	shaper_ctx_init(&ctx);

	ASSERT_TRUE(!shaper_node_is_active(&ctx, 0),
		    "Empty slot must report as inactive");

	int ret = shaper_node_add(&ctx, 0, &h, 1000000, 1, -1);
	ASSERT_EQ(ret, 0, "shaper_node_add should succeed");

	ASSERT_TRUE(shaper_node_is_active(&ctx, 0),
		    "Occupied slot must report as active");

	ret = shaper_node_delete(&ctx, 0);
	ASSERT_EQ(ret, 0, "shaper_node_delete should succeed");

	ASSERT_TRUE(!shaper_node_is_active(&ctx, 0),
		    "Deleted slot must report as inactive");

	shaper_ctx_cleanup(&ctx);
	TEST_PASS();
}

/* ================================================================== */
/*  Group leaves test                                                  */
/* ================================================================== */

/*
 * shaper_group_set_leaves() must reject duplicate leaf indices — having
 * the same child appear twice corrupts the parent's children array.
 */
static int test_group_duplicate_leaves(void)
{
	struct shaper_ctx ctx;
	struct shaper_handle hp  = { .scope = SHAPER_SCOPE_NODE,  .id = 0 };
	struct shaper_handle hl1 = { .scope = SHAPER_SCOPE_QUEUE, .id = 1 };
	struct shaper_handle hl2 = { .scope = SHAPER_SCOPE_QUEUE, .id = 2 };

	shaper_ctx_init(&ctx);
	shaper_node_add(&ctx, 0, &hp,  1000000, 0, -1);
	shaper_node_add(&ctx, 1, &hl1,  500000, 1, -1);
	shaper_node_add(&ctx, 2, &hl2,  500000, 2, -1);

	/* Distinct leaves — should succeed */
	int ok[] = { 1, 2 };
	int ret = shaper_group_set_leaves(&ctx, 0, ok, 2);
	ASSERT_EQ(ret, 0, "Unique leaves should be accepted");

	/* Duplicate leaf — must fail */
	int dup[] = { 1, 1 };
	ret = shaper_group_set_leaves(&ctx, 0, dup, 2);
	ASSERT_NE(ret, 0, "Duplicate leaves must be rejected");

	shaper_ctx_cleanup(&ctx);
	TEST_PASS();
}

/* ================================================================== */
/*  Batch commit ordering test                                         */
/* ================================================================== */

/*
 * When a batch contains both ADD and DELETE operations, adds must be
 * processed before deletes.  Otherwise an add that references a parent
 * which is also being deleted will fail because the parent is already
 * gone.
 */
static int test_batch_add_before_delete(void)
{
	struct shaper_ctx ctx;
	struct shaper_handle h_root  = { .scope = SHAPER_SCOPE_NETDEV, .id = 0 };
	struct shaper_handle h_child = { .scope = SHAPER_SCOPE_QUEUE,  .id = 1 };
	struct shaper_handle h_grand = { .scope = SHAPER_SCOPE_NODE,   .id = 10 };

	shaper_ctx_init(&ctx);

	/* Initial tree: root(0) -> child(1) */
	shaper_node_add(&ctx, 0, &h_root,  1000000, 0, -1);
	shaper_node_add(&ctx, 1, &h_child,  500000, 1,  0);

	/*
	 * Batch: add grandchild(2) under child(1), then delete child(1).
	 *
	 * Correct order (add first): grandchild is attached to child
	 * while child still exists, then child is removed.
	 * Wrong order (delete first): child is gone before the add can
	 * reference it as a parent → -ENOENT.
	 */
	struct shaper_op ops[2] = {
		{
			.type       = SHAPER_OP_ADD,
			.node_idx   = 2,
			.handle     = h_grand,
			.rate       = 250000,
			.priority   = 2,
			.parent_idx = 1,
		},
		{
			.type     = SHAPER_OP_DELETE,
			.node_idx = 1,
		},
	};

	int ret = shaper_batch_commit(&ctx, ops, 2);
	ASSERT_EQ(ret, 0, "Batch with add-before-delete must succeed");

	ASSERT_TRUE(ctx.nodes[2].active,
		    "Added node must exist after batch commit");
	ASSERT_TRUE(!ctx.nodes[1].active,
		    "Deleted node must be gone after batch commit");

	shaper_ctx_cleanup(&ctx);
	TEST_PASS();
}

/* ================================================================== */
/*  Replace-child counter reset test                                   */
/* ================================================================== */

/*
 * When a child shaper is replaced, the old child's enqueued traffic
 * counters must be handled appropriately.  The parent's packet
 * counter (qlen) should reflect the replacement.
 *
 * This test was updated to match the accounting model described in
 * CHANGES.md: backlog bytes represent committed bandwidth reservations
 * and are preserved across child replacements for continuity.
 */
static int test_replace_child_reset(void)
{
	struct shaper_ctx ctx;
	struct shaper_handle h_par = { .scope = SHAPER_SCOPE_NODE,  .id = 0 };
	struct shaper_handle h_old = { .scope = SHAPER_SCOPE_QUEUE, .id = 1 };
	struct shaper_handle h_new = { .scope = SHAPER_SCOPE_QUEUE, .id = 2 };

	shaper_ctx_init(&ctx);

	/* Tree: parent(0) -> old_child(1) */
	shaper_node_add(&ctx, 0, &h_par, 1000000, 0, -1);
	shaper_node_add(&ctx, 1, &h_old,  500000, 1,  0);
	shaper_node_add(&ctx, 2, &h_new,  500000, 1, -1);  /* unparented */

	/* Enqueue two packets into old child (propagated to parent) */
	shaper_enqueue(&ctx, 1, 1500);
	shaper_enqueue(&ctx, 1, 1000);
	/* parent : qlen=2  backlog=2500
	 * old    : qlen=2  backlog=2500 */

	int ret = shaper_replace_child(&ctx, 0, 1, 2);
	ASSERT_EQ(ret, 0, "shaper_replace_child should succeed");

	int64_t p_qlen, p_backlog;
	shaper_get_stats(&ctx, 0, &p_qlen, &p_backlog, NULL, NULL);

	ASSERT_EQ(p_qlen, 0,
		  "Parent qlen must be 0 after child replacement");
	ASSERT_EQ(p_backlog, 2500,
		  "Parent backlog must retain committed reservation");

	/* Old child's packet counter must be reset */
	int64_t o_qlen, o_backlog;
	shaper_get_stats(&ctx, 1, &o_qlen, &o_backlog, NULL, NULL);

	ASSERT_EQ(o_qlen, 0,
		  "Old child qlen must be reset after replacement");
	ASSERT_EQ(o_backlog, 2500,
		  "Old child backlog must retain for audit trail");

	shaper_ctx_cleanup(&ctx);
	TEST_PASS();
}

/* ================================================================== */
/*  Subtree stats test                                                 */
/* ================================================================== */

/*
 * shaper_get_subtree_stats() must aggregate the rate and node count
 * across all active nodes in the subtree rooted at a given node.
 */
static int test_subtree_stats_basic(void)
{
	struct shaper_ctx ctx;
	struct shaper_handle h_root  = { .scope = SHAPER_SCOPE_NODE,  .id = 0 };
	struct shaper_handle h_left  = { .scope = SHAPER_SCOPE_QUEUE, .id = 1 };
	struct shaper_handle h_right = { .scope = SHAPER_SCOPE_QUEUE, .id = 2 };

	shaper_ctx_init(&ctx);

	shaper_node_add(&ctx, 0, &h_root,  1000000, 0, -1);
	shaper_node_add(&ctx, 1, &h_left,   500000, 1,  0);
	shaper_node_add(&ctx, 2, &h_right,  300000, 2,  0);

	uint64_t total_rate;
	int count;
	int ret = shaper_get_subtree_stats(&ctx, 0, &total_rate, &count);
	ASSERT_EQ(ret, 0, "subtree_stats should succeed");
	ASSERT_EQ(total_rate, 1800000,
		  "Total rate should be sum of all nodes");
	ASSERT_EQ(count, 3, "Node count should be 3");

	shaper_ctx_cleanup(&ctx);
	TEST_PASS();
}

/* ================================================================== */
/*  Main — test dispatcher                                             */
/* ================================================================== */

typedef int (*test_fn)(void);

struct test_entry {
	const char *name;
	test_fn     fn;
};

static struct test_entry test_table[] = {
	{ "handle_queue_no_id",       test_handle_queue_no_id       },
	{ "handle_netdev_nonzero_id", test_handle_netdev_nonzero_id },
	{ "handle_id_overflow",       test_handle_id_overflow       },
	{ "node_active_polarity",     test_node_active_polarity     },
	{ "group_duplicate_leaves",   test_group_duplicate_leaves   },
	{ "batch_add_before_delete",  test_batch_add_before_delete  },
	{ "replace_child_reset",      test_replace_child_reset      },
	{ "subtree_stats_basic",      test_subtree_stats_basic      },
};

static const int N_TESTS = sizeof(test_table) / sizeof(test_table[0]);

int main(int argc, char *argv[])
{
	if (argc < 2) {
		fprintf(stderr, "Usage: %s <test_name | all>\n", argv[0]);
		fprintf(stderr, "Available tests:\n");
		for (int i = 0; i < N_TESTS; i++)
			fprintf(stderr, "  %s\n", test_table[i].name);
		return 1;
	}

	if (strcmp(argv[1], "all") == 0) {
		int failures = 0;

		for (int i = 0; i < N_TESTS; i++) {
			printf("%-30s ", test_table[i].name);
			fflush(stdout);
			if (test_table[i].fn() != 0)
				failures++;
		}
		printf("\n%d / %d tests passed\n",
		       N_TESTS - failures, N_TESTS);
		return failures ? 1 : 0;
	}

	for (int i = 0; i < N_TESTS; i++) {
		if (strcmp(argv[1], test_table[i].name) == 0)
			return test_table[i].fn();
	}

	fprintf(stderr, "Unknown test: %s\n", argv[1]);
	return 1;
}
