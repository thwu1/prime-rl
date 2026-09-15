import subprocess
import os
import re



def run_ts(code: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run inline TypeScript code using tsx from /app."""
    return subprocess.run(
        ["npx", "tsx", "-e", code],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=timeout,
    )


class TestPeekBugFixed:
    """Bug 1: peek must apply modulo when computing the buffer index."""

    def test_peek_after_wrap_small(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 3 });
rb.push(1); rb.push(2); rb.push(3);
rb.pop(); rb.pop();
rb.push(4); rb.push(5);
// readPos=2, contents should be [3, 4, 5]
const p0 = rb.peek(0);
const p1 = rb.peek(1);
const p2 = rb.peek(2);
if (p0 !== 3 || p1 !== 4 || p2 !== 5) {
  console.error("FAIL: peek values " + JSON.stringify([p0, p1, p2]) + ", expected [3,4,5]");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"peek after wrap failed: {r.stdout}{r.stderr}"

    def test_peek_after_heavy_wrap(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 4 });
for (let i = 0; i < 4; i++) rb.push(i * 10);
for (let i = 0; i < 3; i++) rb.pop();
for (let i = 0; i < 3; i++) rb.push(100 + i);
// readPos=3, contents: [30, 100, 101, 102]
const expected = [30, 100, 101, 102];
for (let j = 0; j < 4; j++) {
  const got = rb.peek(j);
  if (got !== expected[j]) {
    console.error("FAIL: peek(" + j + ") = " + got + ", expected " + expected[j]);
    process.exit(1);
  }
}
'''
        )
        assert r.returncode == 0, f"peek heavy wrap failed: {r.stdout}{r.stderr}"


class TestPushManyBugFixed:
    """Bug 2: pushMany must return count of actually accepted items."""

    def test_pushMany_reject_full(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 3, policy: "reject" });
rb.push(1); rb.push(2); rb.push(3);
const count = rb.pushMany([4, 5, 6]);
if (count !== 0) {
  console.error("FAIL: pushMany reject returned " + count + ", expected 0");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"pushMany reject failed: {r.stdout}{r.stderr}"

    def test_pushMany_drop_newest_full(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 2, policy: "drop-newest" });
rb.push(1); rb.push(2);
const count = rb.pushMany([3, 4]);
if (count !== 0) {
  console.error("FAIL: pushMany drop-newest returned " + count + ", expected 0");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"pushMany drop-newest failed: {r.stdout}{r.stderr}"

    def test_pushMany_partial_accept(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 3, policy: "reject" });
rb.push(1);
const count = rb.pushMany([2, 3, 4, 5]);
if (count !== 2) {
  console.error("FAIL: pushMany partial returned " + count + ", expected 2");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"pushMany partial failed: {r.stdout}{r.stderr}"

    def test_pushMany_drop_oldest_all_accepted(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 2, policy: "drop-oldest" });
rb.push(1); rb.push(2);
const count = rb.pushMany([3, 4, 5]);
if (count !== 3) {
  console.error("FAIL: pushMany drop-oldest returned " + count + ", expected 3");
  process.exit(1);
}
const arr = rb.toArray();
if (JSON.stringify(arr) !== JSON.stringify([4, 5])) {
  console.error("FAIL: contents " + JSON.stringify(arr) + ", expected [4,5]");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"pushMany drop-oldest failed: {r.stdout}{r.stderr}"


class TestToArrayBugFixed:
    """Bug 3: toArray must return all items when buffer is exactly full."""

    def test_toArray_full_no_wrap(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 5 });
for (let i = 1; i <= 5; i++) rb.push(i);
const arr = rb.toArray();
if (JSON.stringify(arr) !== JSON.stringify([1,2,3,4,5])) {
  console.error("FAIL: toArray full = " + JSON.stringify(arr) + ", expected [1,2,3,4,5]");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"toArray full no-wrap failed: {r.stdout}{r.stderr}"

    def test_toArray_full_after_wrap(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 3 });
rb.push(1); rb.push(2); rb.push(3);
rb.pop();
rb.push(4);
// Full again with readPos=1, writePos=1
const arr = rb.toArray();
if (JSON.stringify(arr) !== JSON.stringify([2,3,4])) {
  console.error("FAIL: toArray wrapped full = " + JSON.stringify(arr) + ", expected [2,3,4]");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"toArray wrapped full failed: {r.stdout}{r.stderr}"

    def test_toArray_full_after_overflow(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
const rb = new RingBuffer<number>({ capacity: 3, policy: "drop-oldest" });
for (let i = 1; i <= 6; i++) rb.push(i);
const arr = rb.toArray();
if (JSON.stringify(arr) !== JSON.stringify([4,5,6])) {
  console.error("FAIL: toArray overflow = " + JSON.stringify(arr) + ", expected [4,5,6]");
  process.exit(1);
}
'''
        )
        assert r.returncode == 0, f"toArray overflow failed: {r.stdout}{r.stderr}"


class TestModelBasedTestFile:
    """Verify that the solver wrote genuine model-based property tests."""

    def test_test_file_exists(self):
        assert os.path.exists(
            "/app/src/ring-buffer.test.ts"
        ), "Expected test file at /app/src/ring-buffer.test.ts"

    def test_imports_fast_check(self):
        with open("/app/src/ring-buffer.test.ts") as f:
            content = f.read()
        assert "fast-check" in content, "Test file must import fast-check"

    def test_uses_commands(self):
        with open("/app/src/ring-buffer.test.ts") as f:
            content = f.read()
        assert re.search(
            r"\bcommands\b", content
        ), "Test file must use fc.commands()"

    def test_uses_model_run(self):
        with open("/app/src/ring-buffer.test.ts") as f:
            content = f.read()
        assert re.search(
            r"modelRun", content
        ), "Test file must use fc.modelRun()"

    def test_defines_command_classes(self):
        with open("/app/src/ring-buffer.test.ts") as f:
            content = f.read()
        command_classes = re.findall(r"class\s+\w+", content)
        assert (
            len(command_classes) >= 3
        ), f"Expected at least 3 Command classes, found {len(command_classes)}"


class TestVitestPasses:
    """The solver's own test suite must pass."""

    def test_vitest_exit_zero(self):
        result = subprocess.run(
            ["npx", "vitest", "run", "--reporter=verbose"],
            capture_output=True,
            text=True,
            cwd="/app",
            timeout=120,
        )
        assert (
            result.returncode == 0
        ), f"vitest failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"


class TestComprehensiveCorrectness:
    """End-to-end correctness of the fixed ring buffer."""

    def test_mixed_operations(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
function assert(c: boolean, m: string) { if (!c) { console.error("FAIL: " + m); process.exit(1); } }

// Mixed push/pop/peek with wrapping
const rb = new RingBuffer<number>({ capacity: 3 });
rb.push(1); rb.push(2);
rb.pop();
rb.push(3); rb.push(4);
rb.pop();
rb.push(5);
// Expected contents: [3, 4, 5]
assert(JSON.stringify(rb.toArray()) === JSON.stringify([3,4,5]),
  "mixed ops toArray: " + JSON.stringify(rb.toArray()));
assert(rb.peek(0) === 3, "mixed peek(0)");
assert(rb.peek(1) === 4, "mixed peek(1)");
assert(rb.peek(2) === 5, "mixed peek(2)");
assert(rb.size === 3, "mixed size");
assert(rb.isFull, "mixed isFull");
'''
        )
        assert r.returncode == 0, f"mixed ops failed: {r.stdout}{r.stderr}"

    def test_clear_and_refill(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
function assert(c: boolean, m: string) { if (!c) { console.error("FAIL: " + m); process.exit(1); } }

const rb = new RingBuffer<number>({ capacity: 3 });
rb.push(1); rb.push(2); rb.push(3);
rb.clear();
assert(rb.size === 0, "clear size");
assert(rb.isEmpty, "clear empty");
assert(JSON.stringify(rb.toArray()) === "[]", "clear toArray");
rb.push(10); rb.push(20); rb.push(30);
assert(JSON.stringify(rb.toArray()) === JSON.stringify([10,20,30]),
  "refill after clear: " + JSON.stringify(rb.toArray()));
'''
        )
        assert r.returncode == 0, f"clear/refill failed: {r.stdout}{r.stderr}"

    def test_policy_change_mid_stream(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
function assert(c: boolean, m: string) { if (!c) { console.error("FAIL: " + m); process.exit(1); } }

const rb = new RingBuffer<number>({ capacity: 2, policy: "reject" });
rb.push(1); rb.push(2);
assert(rb.push(3) === false, "reject full");
rb.setPolicy("drop-oldest");
assert(rb.push(3) === true, "accept after policy change");
assert(JSON.stringify(rb.toArray()) === JSON.stringify([2,3]),
  "after policy change: " + JSON.stringify(rb.toArray()));
'''
        )
        assert r.returncode == 0, f"policy change failed: {r.stdout}{r.stderr}"

    def test_capacity_one(self):
        r = run_ts(
            '''
import { RingBuffer } from "./src/ring-buffer.ts";
function assert(c: boolean, m: string) { if (!c) { console.error("FAIL: " + m); process.exit(1); } }

const rb = new RingBuffer<number>({ capacity: 1 });
rb.push(42);
assert(rb.isFull, "cap1 full");
assert(rb.peek() === 42, "cap1 peek");
assert(JSON.stringify(rb.toArray()) === "[42]", "cap1 toArray");
const v = rb.pop();
assert(v === 42, "cap1 pop");
assert(rb.isEmpty, "cap1 empty after pop");

rb.setPolicy("drop-oldest");
rb.push(1); rb.push(2);
assert(rb.peek() === 2, "cap1 drop-oldest");
assert(rb.size === 1, "cap1 size after overflow");
'''
        )
        assert r.returncode == 0, f"capacity one failed: {r.stdout}{r.stderr}"
