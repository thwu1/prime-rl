
"""
Tests for the compacting GC conversion task.

Verifies:
  1. Source code contains compacting implementation indicators
  2. The original test driver compiles and produces correct output
  3. Heap compaction is physically occurring (objects contiguous after GC)
  4. Multiple GC cycles work correctly
  5. No memory errors or leaks under Valgrind
"""

import subprocess
import os
import re
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd, **kwargs):
    """Run a command and return the CompletedProcess."""
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=120, **kwargs
    )


@pytest.fixture(scope="module")
def compiled():
    """Compile the project once for all tests in this module."""
    run(["make", "-C", "/app", "clean"])
    result = run(["make", "-C", "/app"])
    assert result.returncode == 0, (
        f"Compilation failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert os.path.isfile("/app/vm_test"), "Binary /app/vm_test not produced"
    return True


# ---------------------------------------------------------------------------
# Source-code analysis
# ---------------------------------------------------------------------------

class TestSourceAnalysis:
    """Check that the implementation is actually compacting, not mark-sweep."""

    @pytest.fixture(autouse=True)
    def _read_sources(self):
        with open("/app/vm.h") as f:
            self.header = f.read()
        with open("/app/vm.c") as f:
            self.impl = f.read()
        self.combined = self.header + self.impl

    def test_has_forwarding_address(self):
        """Object struct must have a forwarding-address field."""
        assert re.search(r"forwarding", self.combined, re.IGNORECASE), (
            "Expected a forwarding-address field (e.g. forwardingAddr) in the "
            "Object struct for compacting GC."
        )

    def test_has_compaction_logic(self):
        """vm.c must contain compaction-related code."""
        indicators = ["compact", "memmove", "calculate", "updateref",
                       "update_ref", "update_all", "updateall"]
        found = [w for w in indicators if w.lower() in self.impl.lower()]
        assert len(found) >= 2, (
            f"Expected compaction phases (compact, memmove, calculate, "
            f"updateReferences). Only found: {found}"
        )

    def test_no_per_object_free(self):
        """Compacting GC should not free individual objects."""
        free_calls = re.findall(r"\bfree\s*\(", self.impl)
        assert len(free_calls) <= 1, (
            f"Found {len(free_calls)} free() calls in vm.c. "
            f"Compacting GC should not free individual objects."
        )

    def test_contiguous_heap(self):
        """Implementation should use a contiguous heap, not a linked list."""
        has_heap = bool(re.search(r"\bheap\b", self.combined, re.IGNORECASE))
        assert has_heap, "Expected a contiguous heap (e.g. Object heap[])"

    def test_nan_boxing_preserved(self):
        """NaN-boxing macros must still be present in vm.h."""
        required = [
            "SIGN_BIT", "QNAN", "IS_OBJ", "AS_OBJ", "OBJ_VAL",
            "IS_NUMBER", "NUMBER_VAL", "IS_NIL", "NIL_VAL",
        ]
        for macro in required:
            assert macro in self.header, (
                f"NaN-boxing macro {macro} must be preserved in vm.h"
            )

    def test_object_fields_preserved(self):
        """Object must retain type, intValue, head, tail fields."""
        for field in ["type", "intValue", "head", "tail"]:
            assert field in self.header, (
                f"Object field '{field}' must be preserved in vm.h"
            )


# ---------------------------------------------------------------------------
# Functional tests (run the main test driver)
# ---------------------------------------------------------------------------

class TestMainDriver:
    """Compile and run main.c, verify expected output."""

    @pytest.fixture(autouse=True)
    def _run(self, compiled):
        result = run(["/app/vm_test"])
        self.output = result.stdout
        self.returncode = result.returncode
        self.stderr = result.stderr

    def test_exit_code(self):
        assert self.returncode == 0, (
            f"vm_test exited with code {self.returncode}\n"
            f"stderr: {self.stderr}"
        )

    def test_all_tests_passed(self):
        assert "ALL TESTS PASSED" in self.output, (
            f"Expected 'ALL TESTS PASSED' in output.\n"
            f"Actual output:\n{self.output}"
        )

    def test_basic_allocation(self):
        assert "v1 = Int(42)" in self.output
        assert "v2 = Int(17)" in self.output

    def test_pair_allocation(self):
        assert "pair = Pair(Int(1), Int(2))" in self.output

    def test_gc_preserves_reachable(self):
        assert "pair1 = Pair(Int(10), Int(20))" in self.output
        assert "pair2 = Pair(Int(30), Int(40))" in self.output

    def test_gc_collects_unreachable(self):
        assert "v = Int(3)" in self.output

    def test_nested_pairs(self):
        assert "outer = Pair(Pair(Int(1), Int(2)), Int(3))" in self.output

    def test_mixed_nan_boxed_values(self):
        assert "result = Pair(Pair(3.14, Int(99)), Pair(nil, true))" in self.output

    def test_stress_linked_list(self):
        assert "(total=100)" in self.output
        assert re.search(r"list:\s*0\s+1\s+2\s+3\s+4", self.output), (
            "Stress test should produce list starting with 0 1 2 3 4"
        )

    def test_post_gc_allocation(self):
        assert "bottom = Int(100)" in self.output
        assert "pair_top = Pair(Int(400), Int(500))" in self.output


# ---------------------------------------------------------------------------
# Compaction behaviour test
# ---------------------------------------------------------------------------

COMPACT_TEST_SRC = r"""
#include "vm.h"
#include <stdio.h>
#include <stddef.h>
#include <stdlib.h>

int main(void) {
    VM* vm = newVM();

    /* Allocate four Int objects: A B C D (in that order). */
    pushInt(vm, 1);   /* A */
    pushInt(vm, 2);   /* B - will become garbage */
    pushInt(vm, 3);   /* C - will become garbage */
    pushInt(vm, 4);   /* D */

    /* Keep only A and D on the stack. */
    Value d = pop(vm);     /* D */
    pop(vm);               /* discard C */
    pop(vm);               /* discard B */
    push(vm, d);           /* stack: [A, D] */

    gc(vm);                /* Should compact: A D (contiguous) */

    /* Allocate E right after compacted region. */
    pushInt(vm, 5);        /* E */

    Object* a  = AS_OBJ(peek(vm, 2));
    Object* d2 = AS_OBJ(peek(vm, 1));
    Object* e  = AS_OBJ(peek(vm, 0));

    /* Values must survive compaction. */
    if (a->intValue == 1 && d2->intValue == 4 && e->intValue == 5) {
        printf("VALUES_OK\n");
    } else {
        printf("VALUES_FAIL: a=%d d=%d e=%d\n",
               a->intValue, d2->intValue, e->intValue);
    }

    /* After compaction, A-D-E should be contiguous with stride sizeof(Object). */
    ptrdiff_t ad = (char*)d2 - (char*)a;
    ptrdiff_t de = (char*)e  - (char*)d2;

    if (ad == (ptrdiff_t)sizeof(Object) && de == (ptrdiff_t)sizeof(Object)) {
        printf("COMPACT_OK\n");
    } else {
        printf("COMPACT_FAIL: ad=%td de=%td sizeof=%zu\n",
               ad, de, sizeof(Object));
    }

    pop(vm); pop(vm); pop(vm);
    freeVM(vm);
    return 0;
}
"""


class TestCompaction:
    """Compile and run a dedicated compaction test."""

    @pytest.fixture(autouse=True)
    def _build_and_run(self, compiled):
        src_path = "/app/_test_compact.c"
        bin_path = "/app/_test_compact"
        with open(src_path, "w") as f:
            f.write(COMPACT_TEST_SRC)

        result = run([
            "gcc", "-Wall", "-Wextra", "-g", "-O0", "-std=c11",
            "-o", bin_path, src_path, "/app/vm.c", "-I/app"
        ])
        assert result.returncode == 0, (
            f"Compaction test compilation failed:\n{result.stderr}"
        )

        result = run([bin_path])
        self.output = result.stdout
        self.returncode = result.returncode
        self.stderr = result.stderr

    def test_exit_code(self):
        assert self.returncode == 0, (
            f"Compaction test crashed:\nstderr: {self.stderr}"
        )

    def test_values_preserved(self):
        assert "VALUES_OK" in self.output, (
            f"Values not preserved through compaction:\n{self.output}"
        )

    def test_objects_contiguous(self):
        assert "COMPACT_OK" in self.output, (
            f"Objects not contiguous after compaction:\n{self.output}"
        )


# ---------------------------------------------------------------------------
# Multi-cycle GC stress test
# ---------------------------------------------------------------------------

MULTI_GC_TEST_SRC = r"""
#include "vm.h"
#include <stdio.h>

int main(void) {
    VM* vm = newVM();
    int errors = 0;

    /*
     * Repeatedly allocate garbage then one keeper, forcing many GC cycles.
     * After each round, verify the keeper is intact.
     */
    for (int round = 0; round < 50; round++) {
        /* Create garbage. */
        for (int j = 0; j < 10; j++) {
            pushInt(vm, -1);
            pop(vm);
        }

        /* Create a keeper. */
        pushInt(vm, round);
        pushInt(vm, round * 10);
        pushPair(vm);           /* Pair(round, round*10) */
    }

    /* Force a final GC. */
    gc(vm);

    /* Verify all 50 pairs survived with correct values. */
    for (int round = 49; round >= 0; round--) {
        Value v = peek(vm, 49 - round);
        if (!IS_OBJ(v)) { errors++; continue; }
        Object* p = AS_OBJ(v);
        if (p->type != OBJ_PAIR) { errors++; continue; }
        if (!IS_OBJ(p->head)) { errors++; continue; }
        Object* h = AS_OBJ(p->head);
        if (h->intValue != round) { errors++; continue; }
        if (!IS_OBJ(p->tail)) { errors++; continue; }
        Object* t = AS_OBJ(p->tail);
        if (t->intValue != round * 10) { errors++; continue; }
    }

    /* Clean up. */
    for (int i = 0; i < 50; i++) pop(vm);
    freeVM(vm);

    if (errors == 0) {
        printf("MULTI_GC_OK\n");
    } else {
        printf("MULTI_GC_FAIL: %d errors\n", errors);
    }
    return 0;
}
"""


class TestMultiGcCycles:
    """Stress test with many GC cycles and interleaved allocation."""

    @pytest.fixture(autouse=True)
    def _build_and_run(self, compiled):
        src_path = "/app/_test_multi_gc.c"
        bin_path = "/app/_test_multi_gc"
        with open(src_path, "w") as f:
            f.write(MULTI_GC_TEST_SRC)

        result = run([
            "gcc", "-Wall", "-Wextra", "-g", "-O0", "-std=c11",
            "-o", bin_path, src_path, "/app/vm.c", "-I/app"
        ])
        assert result.returncode == 0, (
            f"Multi-GC test compilation failed:\n{result.stderr}"
        )

        result = run([bin_path])
        self.output = result.stdout
        self.returncode = result.returncode
        self.stderr = result.stderr

    def test_exit_code(self):
        assert self.returncode == 0, (
            f"Multi-GC test crashed:\nstderr: {self.stderr}"
        )

    def test_values_correct(self):
        assert "MULTI_GC_OK" in self.output, (
            f"Multi-cycle GC test failed:\n{self.output}"
        )


# ---------------------------------------------------------------------------
# Valgrind memory analysis tests
# ---------------------------------------------------------------------------

class TestValgrind:
    """Run under Valgrind memcheck and verify no memory errors or leaks."""

    @pytest.fixture(autouse=True)
    def _build_and_run(self, compiled):
        result = run([
            "valgrind",
            "--leak-check=full",
            "--error-exitcode=99",
            "/app/vm_test"
        ])
        self.output = result.stdout
        self.returncode = result.returncode
        self.stderr = result.stderr

    def test_no_memory_errors(self):
        """Valgrind must not detect invalid reads, writes, or other errors."""
        assert self.returncode != 99, (
            f"Valgrind found memory errors:\n{self.stderr}"
        )

    def test_exit_code(self):
        """Program must exit cleanly under Valgrind."""
        assert self.returncode == 0, (
            f"Valgrind run exited with code {self.returncode}\n"
            f"stderr:\n{self.stderr}"
        )

    def test_no_definite_leaks(self):
        """No definite memory leaks allowed."""
        assert "definitely lost: 0 bytes" in self.stderr or \
               "no leaks are possible" in self.stderr, (
            f"Valgrind detected memory leaks:\n{self.stderr}"
        )

    def test_correct_output(self):
        """Binary must produce correct output under Valgrind."""
        assert "ALL TESTS PASSED" in self.output, (
            f"Binary did not produce correct output under Valgrind:\n{self.output}"
        )
