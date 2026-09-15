
import subprocess
import os
import pytest


def _tsx(code: str, timeout: int = 30) -> str:
    """Write TypeScript to a temp file under /app and run with tsx."""
    test_file = "/app/__test_tmp.ts"
    with open(test_file, "w") as f:
        f.write(code)
    try:
        result = subprocess.run(
            ["npx", "tsx", test_file],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/app",
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"tsx exit code {result.returncode}\n"
                f"stderr: {result.stderr}\n"
                f"stdout: {result.stdout}"
            )
        return result.stdout.strip()
    finally:
        if os.path.exists(test_file):
            os.unlink(test_file)


# ═══════════════════════════════════════════════════════════════════════
# BUILD PIPELINE TESTS
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="module")
def tsc_result():
    return subprocess.run(
        ["npx", "tsc", "--noEmit"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture(scope="module")
def build_result():
    return subprocess.run(
        ["node", "build.mjs"],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_typecheck(tsc_result):
    """tsc --noEmit must exit 0."""
    assert tsc_result.returncode == 0, (
        f"TypeScript type-check failed:\n{tsc_result.stdout}\n{tsc_result.stderr}"
    )


def test_build(build_result):
    """build.mjs must produce dist/index.mjs."""
    assert build_result.returncode == 0, (
        f"Build failed:\n{build_result.stdout}\n{build_result.stderr}"
    )
    assert os.path.isfile("/app/dist/index.mjs"), "dist/index.mjs not produced"


def test_bundle_exports(build_result):
    """Built bundle must export all required public API symbols."""
    if build_result.returncode != 0 or not os.path.isfile("/app/dist/index.mjs"):
        pytest.skip("Build not available")
    output = _tsx(
        """
import { createSignal, createEffect, createMemo, batch, createRoot, untrack, onCleanup } from './dist/index.mjs';
import { createStore } from './dist/index.mjs';
const fns = [createSignal, createEffect, createMemo, batch, createRoot, untrack, onCleanup, createStore];
console.log(fns.every(f => typeof f === 'function') ? 'EXPORTS_OK' : 'EXPORTS_MISSING');
"""
    )
    assert "EXPORTS_OK" in output, f"Missing bundle exports: {output}"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — SIGNALS
# ═══════════════════════════════════════════════════════════════════════


def test_signal_read_write():
    output = _tsx(
        """
import { createSignal } from './src/reactive.ts';
const [count, setCount] = createSignal(0);
console.log(count());
setCount(5);
console.log(count());
setCount((prev: number) => prev * 2);
console.log(count());
"""
    )
    assert output == "0\n5\n10"


def test_signal_no_trigger_on_same_value():
    output = _tsx(
        """
import { createSignal, createEffect } from './src/reactive.ts';
const [count, setCount] = createSignal(0);
let runs = 0;
createEffect(() => { runs++; count(); });
setCount(0);
setCount(0);
setCount(1);
console.log(runs);
"""
    )
    assert output == "2", f"Expected 2 (initial + one real change), got {output}"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — EFFECTS
# ═══════════════════════════════════════════════════════════════════════


def test_effect_auto_tracking():
    output = _tsx(
        """
import { createSignal, createEffect } from './src/reactive.ts';
const [count, setCount] = createSignal(0);
const log: string[] = [];
createEffect(() => { log.push('effect:' + count()); });
setCount(1);
setCount(2);
console.log(log.join(','));
"""
    )
    assert output == "effect:0,effect:1,effect:2"


def test_effect_dynamic_dependencies():
    output = _tsx(
        """
import { createSignal, createEffect } from './src/reactive.ts';
const [showB, setShowB] = createSignal(true);
const [a, setA] = createSignal('a1');
const [b, setB] = createSignal('b1');

let runs = 0;
createEffect(() => {
  runs++;
  const val = showB() ? b() : a();
  console.log('val=' + val + ',runs=' + runs);
});

setB('b2');
setShowB(false);
setA('a2');
setB('b3');
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "val=b1,runs=1"
    assert lines[1] == "val=b2,runs=2"
    assert lines[2] == "val=a1,runs=3"
    assert lines[3] == "val=a2,runs=4"
    assert len(lines) == 4, f"setB('b3') should not trigger; got {len(lines)} lines"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — MEMOS
# ═══════════════════════════════════════════════════════════════════════


def test_memo_basic():
    output = _tsx(
        """
import { createSignal, createMemo } from './src/reactive.ts';
const [count, setCount] = createSignal(3);
const double = createMemo(() => count() * 2);
console.log(double());
setCount(5);
console.log(double());
"""
    )
    assert output == "6\n10"


def test_memo_chain():
    output = _tsx(
        """
import { createSignal, createMemo, createEffect } from './src/reactive.ts';
const [x, setX] = createSignal(1);
const a = createMemo(() => x() + 1);
const b = createMemo(() => a() + 1);
const c = createMemo(() => b() + 1);

let runs = 0;
createEffect(() => {
  runs++;
  console.log('c=' + c() + ',runs=' + runs);
});

setX(10);
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "c=4,runs=1"
    assert lines[1] == "c=13,runs=2"
    assert len(lines) == 2


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — GLITCH-FREE DIAMOND
# ═══════════════════════════════════════════════════════════════════════


def test_diamond_glitch_free():
    """Classic diamond: a->b, a->c. Effect reads b()+c(). Must run once per update."""
    output = _tsx(
        """
import { createSignal, createMemo, createEffect } from './src/reactive.ts';
const [a, setA] = createSignal(1);
const b = createMemo(() => a() * 2);
const c = createMemo(() => a() * 3);
const sum = createMemo(() => b() + c());

let runs = 0;
createEffect(() => {
  runs++;
  console.log('sum=' + sum() + ',runs=' + runs);
});

setA(2);
setA(3);
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "sum=5,runs=1", f"Initial: {lines[0]}"
    assert lines[1] == "sum=10,runs=2", f"After setA(2): {lines[1]}"
    assert lines[2] == "sum=15,runs=3", f"After setA(3): {lines[2]}"
    assert len(lines) == 3, f"Expected exactly 3 executions, got {len(lines)}"


def test_deep_diamond():
    """Deeper diamond: a->b, a->c->d, effect reads b()+d()."""
    output = _tsx(
        """
import { createSignal, createMemo, createEffect } from './src/reactive.ts';
const [a, setA] = createSignal(1);
const b = createMemo(() => a() + 1);
const c = createMemo(() => a() + 10);
const d = createMemo(() => c() + 100);
const e = createMemo(() => b() + d());

let runs = 0;
createEffect(() => {
  runs++;
  console.log('e=' + e() + ',runs=' + runs);
});

setA(2);
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "e=113,runs=1", f"Initial: {lines[0]}"
    assert lines[1] == "e=115,runs=2", f"After setA(2): {lines[1]}"
    assert len(lines) == 2


def test_wide_diamond():
    """Wide diamond: many memos from same signal converge."""
    output = _tsx(
        """
import { createSignal, createMemo, createEffect } from './src/reactive.ts';
const [x, setX] = createSignal(1);
const m1 = createMemo(() => x() + 1);
const m2 = createMemo(() => x() + 2);
const m3 = createMemo(() => x() + 3);
const m4 = createMemo(() => x() + 4);
const total = createMemo(() => m1() + m2() + m3() + m4());

let runs = 0;
createEffect(() => {
  runs++;
  console.log('total=' + total() + ',runs=' + runs);
});

setX(10);
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "total=14,runs=1"
    assert lines[1] == "total=50,runs=2"
    assert len(lines) == 2


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — MEMO EQUALITY CUTOFF
# ═══════════════════════════════════════════════════════════════════════


def test_memo_equality_no_propagation():
    """If memo value unchanged, downstream must NOT re-run."""
    output = _tsx(
        """
import { createSignal, createMemo, createEffect } from './src/reactive.ts';
const [a, setA] = createSignal(1);
const isPositive = createMemo(() => a() > 0);

let runs = 0;
createEffect(() => {
  runs++;
  console.log('pos=' + isPositive() + ',runs=' + runs);
});

setA(2);
setA(5);
setA(-1);
setA(-3);
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "pos=true,runs=1"
    assert lines[1] == "pos=false,runs=2"
    assert len(lines) == 2, f"Effect should only run when memo value changes, got {len(lines)}"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — BATCH
# ═══════════════════════════════════════════════════════════════════════


def test_batch_deferred():
    output = _tsx(
        """
import { createSignal, createEffect, batch } from './src/reactive.ts';
const [a, setA] = createSignal(1);
const [b, setB] = createSignal(10);

let runs = 0;
createEffect(() => {
  runs++;
  console.log('sum=' + (a() + b()) + ',runs=' + runs);
});

batch(() => {
  setA(2);
  setB(20);
});
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "sum=11,runs=1"
    assert lines[1] == "sum=22,runs=2"
    assert len(lines) == 2, f"Batch must produce single effect execution, got {len(lines)}"


def test_batch_with_memos():
    output = _tsx(
        """
import { createSignal, createMemo, createEffect, batch } from './src/reactive.ts';
const [a, setA] = createSignal(1);
const [b, setB] = createSignal(10);
const sum = createMemo(() => a() + b());
const product = createMemo(() => a() * b());

let runs = 0;
createEffect(() => {
  runs++;
  console.log(sum() + ':' + product() + ',runs=' + runs);
});

batch(() => {
  setA(2);
  setB(20);
});
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "11:10,runs=1"
    assert lines[1] == "22:40,runs=2"
    assert len(lines) == 2


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — OWNERSHIP / DISPOSAL
# ═══════════════════════════════════════════════════════════════════════


def test_create_root_disposal():
    output = _tsx(
        """
import { createSignal, createEffect, createRoot } from './src/reactive.ts';
const [count, setCount] = createSignal(0);
const log: string[] = [];

let disposer!: () => void;
createRoot(dispose => {
  disposer = dispose;
  createEffect(() => { log.push('effect:' + count()); });
});

setCount(1);
disposer();
setCount(2);
setCount(3);
console.log(log.join(','));
"""
    )
    assert output == "effect:0,effect:1", f"After disposal, effect must not run. Got: {output}"


def test_nested_effects_disposal():
    """Inner effects are disposed when parent re-executes."""
    output = _tsx(
        """
import { createSignal, createEffect, createRoot } from './src/reactive.ts';
const [outer, setOuter] = createSignal('a');
const [inner, setInner] = createSignal('x');
const log: string[] = [];

createRoot(() => {
  createEffect(() => {
    const o = outer();
    log.push('outer:' + o);
    createEffect(() => {
      log.push('inner:' + o + ':' + inner());
    });
  });
});

setInner('y');
setOuter('b');
setInner('z');
console.log(log.join(','));
"""
    )
    assert output == "outer:a,inner:a:x,inner:a:y,outer:b,inner:b:y,inner:b:z", f"Got: {output}"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — UNTRACK
# ═══════════════════════════════════════════════════════════════════════


def test_untrack():
    output = _tsx(
        """
import { createSignal, createEffect, untrack } from './src/reactive.ts';
const [a, setA] = createSignal(1);
const [b, setB] = createSignal(10);

let runs = 0;
createEffect(() => {
  runs++;
  const aVal = a();
  const bVal = untrack(() => b());
  console.log('a=' + aVal + ',b=' + bVal + ',runs=' + runs);
});

setA(2);
setB(20);
setA(3);
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "a=1,b=10,runs=1"
    assert lines[1] == "a=2,b=10,runs=2"
    assert lines[2] == "a=3,b=20,runs=3"
    assert len(lines) == 3, f"setB should not trigger effect; got {len(lines)} lines"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — CLEANUP
# ═══════════════════════════════════════════════════════════════════════


def test_on_cleanup_re_execution():
    output = _tsx(
        """
import { createSignal, createEffect, onCleanup } from './src/reactive.ts';
const [count, setCount] = createSignal(0);
const log: string[] = [];

createEffect(() => {
  const c = count();
  onCleanup(() => log.push('cleanup:' + c));
  log.push('effect:' + c);
});

setCount(1);
setCount(2);
console.log(log.join(','));
"""
    )
    assert output == "effect:0,cleanup:0,effect:1,cleanup:1,effect:2", f"Got: {output}"


def test_cleanup_on_disposal():
    output = _tsx(
        """
import { createSignal, createEffect, createRoot, onCleanup } from './src/reactive.ts';
const log: string[] = [];

let disposer!: () => void;
createRoot(dispose => {
  disposer = dispose;
  createEffect(() => {
    log.push('effect');
    onCleanup(() => log.push('disposed'));
  });
});

log.push('before-dispose');
disposer();
log.push('after-dispose');
console.log(log.join(','));
"""
    )
    assert output == "effect,before-dispose,disposed,after-dispose", f"Got: {output}"


# ═══════════════════════════════════════════════════════════════════════
# REACTIVE CORE — COMBINED STRESS
# ═══════════════════════════════════════════════════════════════════════


def test_batch_diamond_combined():
    """Batch + diamond + memo equality combined."""
    output = _tsx(
        """
import { createSignal, createMemo, createEffect, batch } from './src/reactive.ts';
const [x, setX] = createSignal(5);
const [y, setY] = createSignal(10);

const xSign = createMemo(() => x() >= 0 ? 'pos' : 'neg');
const ySign = createMemo(() => y() >= 0 ? 'pos' : 'neg');
const label = createMemo(() => xSign() + '/' + ySign());

let runs = 0;
createEffect(() => {
  runs++;
  console.log(label() + ',runs=' + runs);
});

batch(() => {
  setX(100);
  setY(200);
});

setX(-1);

batch(() => {
  setX(1);
  setY(-1);
});
"""
    )
    lines = output.strip().split("\n")
    assert lines[0] == "pos/pos,runs=1"
    assert lines[1] == "neg/pos,runs=2"
    assert lines[2] == "pos/neg,runs=3"
    assert len(lines) == 3, f"Expected 3 executions, got {len(lines)}"


# ═══════════════════════════════════════════════════════════════════════
# STORE — BASIC REACTIVITY
# ═══════════════════════════════════════════════════════════════════════


def test_store_basic_reactivity():
    """Store property reads must be tracked in effects."""
    output = _tsx(
        """
import { createEffect, createRoot } from './src/reactive.ts';
import { createStore } from './src/store.ts';
const [store, setStore] = createStore({ count: 0, label: 'hello' });
const log: string[] = [];
createRoot(() => {
  createEffect(() => { log.push('count:' + store.count); });
  setStore('count', 1);
  setStore('count', 2);
  console.log(log.join(','));
});
"""
    )
    assert output == "count:0,count:1,count:2", f"Got: {output}"


def test_store_nested_tracking():
    """Nested object properties must be reactively tracked."""
    output = _tsx(
        """
import { createEffect, createRoot } from './src/reactive.ts';
import { createStore } from './src/store.ts';
const [store, setStore] = createStore({ user: { name: 'Alice', age: 30 } });
const log: string[] = [];
createRoot(() => {
  createEffect(() => { log.push('name:' + store.user.name); });
  setStore('user', 'name', 'Bob');
  console.log(log.join(','));
});
"""
    )
    assert output == "name:Alice,name:Bob", f"Got: {output}"


def test_store_path_setter():
    """setStore path setter must handle multi-level nesting."""
    output = _tsx(
        """
import { createEffect, createRoot } from './src/reactive.ts';
import { createStore } from './src/store.ts';
const [store, setStore] = createStore({
  config: { db: { host: 'localhost', port: 5432 } }
});
const log: string[] = [];
createRoot(() => {
  createEffect(() => { log.push('host:' + store.config.db.host); });
  setStore('config', 'db', 'host', 'remote.example.com');
  console.log(log.join(','));
});
"""
    )
    assert output == "host:localhost,host:remote.example.com", f"Got: {output}"


def test_store_updater_batch():
    """setStore with updater function must batch multiple property changes."""
    output = _tsx(
        """
import { createEffect, createRoot } from './src/reactive.ts';
import { createStore } from './src/store.ts';
const [store, setStore] = createStore({ a: 1, b: 2 });
const log: string[] = [];
createRoot(() => {
  createEffect(() => { log.push('sum:' + (store.a + store.b)); });
  setStore((s: any) => { s.a = 10; s.b = 20; });
  console.log(log.join(','));
});
"""
    )
    # Initial sum:3, then after batch update sum:30 (not intermediate)
    assert output == "sum:3,sum:30", f"Got: {output}"


def test_store_effect_independence():
    """Changing one property must not trigger effects for unrelated properties."""
    output = _tsx(
        """
import { createEffect, createRoot } from './src/reactive.ts';
import { createStore } from './src/store.ts';
const [store, setStore] = createStore({ x: 1, y: 10 });
let xRuns = 0;
let yRuns = 0;
createRoot(() => {
  createEffect(() => { xRuns++; store.x; });
  createEffect(() => { yRuns++; store.y; });
  setStore('x', 2);
  setStore('x', 3);
  setStore('y', 20);
  console.log('xRuns:' + xRuns + ',yRuns:' + yRuns);
});
"""
    )
    # x effect: initial + 2 updates = 3, y effect: initial + 1 update = 2
    assert output == "xRuns:3,yRuns:2", f"Got: {output}"


# ═══════════════════════════════════════════════════════════════════════
# STORE + REACTIVE INTEGRATION
# ═══════════════════════════════════════════════════════════════════════


def test_store_with_memo():
    """createMemo can derive from store properties."""
    output = _tsx(
        """
import { createEffect, createMemo, createRoot } from './src/reactive.ts';
import { createStore } from './src/store.ts';
const [store, setStore] = createStore({ price: 100, qty: 3 });
const log: string[] = [];
createRoot(() => {
  const total = createMemo(() => store.price * store.qty);
  createEffect(() => { log.push('total:' + total()); });
  setStore('qty', 5);
  console.log(log.join(','));
});
"""
    )
    assert output == "total:300,total:500", f"Got: {output}"
