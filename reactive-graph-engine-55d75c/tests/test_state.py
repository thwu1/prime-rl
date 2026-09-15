
import subprocess
import os
import textwrap

ASSERT_HELPER = textwrap.dedent(r'''
function check(cond: boolean, msg: string): void {
  if (!cond) { console.error("FAIL: " + msg); process.exit(1); }
}
''')

IMPORT_LINE = 'import { createSignal, createMemo, createEffect, createRoot, batch, untrack, onCleanup } from "./src/reactive.js";\n'


def run_ts(code: str, timeout: int = 30) -> subprocess.CompletedProcess:
    full_code = IMPORT_LINE + ASSERT_HELPER + textwrap.dedent(code)
    test_file = "/app/_test_tmp.ts"
    with open(test_file, "w") as f:
        f.write(full_code)
    try:
        result = subprocess.run(
            ["npx", "tsx", test_file],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd="/app",
        )
        return result
    finally:
        if os.path.exists(test_file):
            os.unlink(test_file)


# ──────────────────────────────────────────────
# Basic signal tests
# ──────────────────────────────────────────────

def test_basic_signal():
    r = run_ts('''
        const [get, set] = createSignal(5);
        check(get() === 5, "initial value");
        set(10);
        check(get() === 10, "after set");
        set((p: number) => p + 5);
        check(get() === 15, "after fn set");
        console.log("PASS");
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


def test_signal_comparator():
    r = run_ts('''
        const [get, set] = createSignal(5, {
            equals: (a: number, b: number) => a > b,
        });
        set(3);
        check(get() === 5, "comparator blocked update");
        set(10);
        check(get() === 10, "comparator allowed update");
        console.log("PASS");
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Basic memo tests
# ──────────────────────────────────────────────

def test_basic_memo():
    r = run_ts('''
        createRoot((_d: any) => {
            const m = createMemo(() => "Hello");
            check(m() === "Hello", "basic memo value");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


def test_memo_reactive_update():
    r = run_ts('''
        createRoot((_d: any) => {
            const [name, setName] = createSignal("John");
            const greeting = createMemo(() => "Hello " + name());
            check(greeting() === "Hello John", "initial memo");
            setName("Jake");
            check(greeting() === "Hello Jake", "updated memo");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Glitch-free propagation / convergence tests
# ──────────────────────────────────────────────

def test_diamond_convergence():
    """Diamond A->B,C->D: D must evaluate exactly once."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [a, setA] = createSignal(false);
            let seq = "";
            const b1 = createMemo(
                () => { a(); seq += "b1"; return undefined; },
                undefined,
                { equals: false } as any,
            );
            const b2 = createMemo(
                () => { a(); seq += "b2"; return undefined; },
                undefined,
                { equals: false } as any,
            );
            const c1 = createMemo(
                () => { b1(); b2(); seq += "c1"; return undefined; },
                undefined,
                { equals: false } as any,
            );
            seq = "";
            setA(true);
            check(seq === "b1b2c1", "diamond order: got '" + seq + "'");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


def test_linear_convergence():
    """5 fan-out memos from d converge to g. g evaluates once."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [d, setD] = createSignal(0);
            const f1 = createMemo(() => d());
            const f2 = createMemo(() => d());
            const f3 = createMemo(() => d());
            const f4 = createMemo(() => d());
            const f5 = createMemo(() => d());
            let gcount = 0;
            const g = createMemo(() => {
                gcount++;
                return f1() + f2() + f3() + f4() + f5();
            });
            gcount = 0;
            setD(1);
            check(gcount === 1, "linear convergence: g evaluated " + gcount + " times, expected 1");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


def test_exponential_convergence():
    """3-layer diamond with cross connections. Sink h evaluates once."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [d, setD] = createSignal(0);
            const f1 = createMemo(() => d());
            const f2 = createMemo(() => d());
            const f3 = createMemo(() => d());
            const g1 = createMemo(() => f1() + f2() + f3());
            const g2 = createMemo(() => f1() + f2() + f3());
            const g3 = createMemo(() => f1() + f2() + f3());
            let hcount = 0;
            const h = createMemo(() => {
                hcount++;
                return g1() + g2() + g3();
            });
            hcount = 0;
            setD(1);
            check(hcount === 1, "exponential convergence: h evaluated " + hcount + " times, expected 1");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# PENDING / equal-value suppression tests
# ──────────────────────────────────────────────

def test_no_trigger_on_equal_value():
    """Memo that produces the same value should not propagate."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [s1, set] = createSignal(1, { equals: false } as any);
            let order = "";
            const t1 = createMemo(() => { order += "t1"; return s1(); });
            const _c1 = createMemo(() => { order += "c1"; return t1(); });
            order = "";
            set(1);
            check(order === "t1", "equal value no propagation: got '" + order + "'");
            order = "";
            set(2);
            check(order === "t1c1", "changed value propagation: got '" + order + "'");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


def test_intercepting_pending_computations():
    """Pending computations should not re-evaluate if trackers haven't changed."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [s1, set1] = createSignal(1);
            const [s2, set2] = createSignal(false);
            let count = 0;
            const t1 = createMemo(() => s1() > 0);
            const t2 = createMemo(() => s1() > 0);
            const c1 = createMemo(() => s1());
            const t3 = createMemo(() => {
                const a = s1();
                const b = s2();
                return a && b;
            });
            const _c3 = createMemo(() => {
                t1(); t2(); c1(); t3();
                count++;
                return undefined;
            });
            set2(true);
            check(count === 2, "after set2: count=" + count + " expected 2");
            set1(2);
            check(count === 3, "after set1: count=" + count + " expected 3");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Dynamic dependency tracking tests
# ──────────────────────────────────────────────

def test_dynamic_deps_active():
    r = run_ts('''
        createRoot((_d: any) => {
            const [i, _setI] = createSignal(true);
            const [t, setT] = createSignal(1);
            const [e, _setE] = createSignal(2);
            let fevals = 0;
            const f = createMemo(() => { fevals++; return i() ? t() : e(); });
            fevals = 0;
            setT(5);
            check(fevals === 1, "active dep update: " + fevals);
            check(f() === 5, "active dep value: " + f());
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


def test_dynamic_deps_inactive():
    r = run_ts('''
        createRoot((_d: any) => {
            const [i, _setI] = createSignal(true);
            const [t, _setT] = createSignal(1);
            const [e, setE] = createSignal(2);
            let fevals = 0;
            const f = createMemo(() => { fevals++; return i() ? t() : e(); });
            fevals = 0;
            setE(5);
            check(fevals === 0, "inactive dep should not trigger: " + fevals);
            check(f() === 1, "value unchanged: " + f());
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


def test_dynamic_deps_deactivate():
    """After switching condition, old deps should be fully detached."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [i, setI] = createSignal(true);
            const [t, setT] = createSignal(1);
            const [e, _setE] = createSignal(2);
            let fevals = 0;
            const f = createMemo(() => { fevals++; return i() ? t() : e(); });
            setI(false);
            fevals = 0;
            setT(5);
            check(fevals === 0, "deactivated dep should not trigger: " + fevals);
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


def test_dynamic_deps_activate():
    """After switching condition, new deps should be activated."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [i, setI] = createSignal(true);
            const [t, _setT] = createSignal(1);
            const [e, setE] = createSignal(2);
            let fevals = 0;
            const f = createMemo(() => { fevals++; return i() ? t() : e(); });
            setI(false);
            fevals = 0;
            setE(5);
            check(fevals === 1, "activated dep should trigger: " + fevals);
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Batch tests
# ──────────────────────────────────────────────

def test_batch_coalesces():
    """batch() should coalesce multiple writes into one update wave."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [a, setA] = createSignal(0);
            const [b, setB] = createSignal(0);
            let count = 0;
            const sum = createMemo(() => { count++; return a() + b(); });
            count = 0;
            batch(() => {
                setA(1);
                setB(1);
            });
            check(count === 1, "batch single evaluation: count=" + count);
            check(sum() === 2, "batch result: " + sum());
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Untrack tests
# ──────────────────────────────────────────────

def test_untrack():
    """Untracked reads should not establish dependencies."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [a, setA] = createSignal(1);
            let count = 0;
            const m = createMemo(() => { count++; return untrack(() => a()); });
            count = 0;
            setA(2);
            check(count === 0, "untrack prevents dependency: " + count);
            check(m() === 1, "untracked value should not update: " + m());
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Cleanup / disposal tests
# ──────────────────────────────────────────────

def test_cleanup():
    """onCleanup callback fires on dispose."""
    r = run_ts('''
        let cleaned = false;
        const dispose = createRoot((dispose: () => void) => {
            onCleanup(() => { cleaned = true; });
            return dispose;
        });
        check(!cleaned, "not yet cleaned");
        dispose();
        check(cleaned, "cleaned after dispose");
        console.log("PASS");
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


def test_root_dispose():
    """Disposing a root must fully detach owned computations."""
    r = run_ts('''
        const [s, setS] = createSignal(0);
        let count = 0;
        const dispose = createRoot((dispose: () => void) => {
            createMemo(() => { count++; return s(); });
            return dispose;
        });
        count = 0;
        setS(1);
        check(count === 1, "reacts before dispose: " + count);
        dispose();
        count = 0;
        setS(2);
        check(count === 0, "must not react after dispose: " + count);
        console.log("PASS");
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Topological order tests
# ──────────────────────────────────────────────

def test_topological_order_chain():
    """s -> t1 -> c1 -> c2 -> c3 all run in order."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [s1, set] = createSignal(1);
            let order = "";
            const t1 = createMemo(() => { order += "t1"; return s1(); });
            const c1 = createMemo(() => { order += "c1"; return t1(); });
            const c2 = createMemo(() => { order += "c2"; return c1(); });
            const _c3 = createMemo(() => { order += "c3"; return c2(); });
            order = "";
            set(2);
            check(order === "t1c1c2c3", "chain order: got '" + order + "'");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


def test_topological_order_diamond():
    """s -> t1,t2 -> c1: order is t1,t2 before c1."""
    r = run_ts('''
        createRoot((_d: any) => {
            const [s1, set] = createSignal(true);
            let order = "";
            const t1 = createMemo(() => { order += "t1"; return s1(); });
            const t2 = createMemo(() => { order += "t2"; return s1(); });
            const _c1 = createMemo(() => { t1(); t2(); order += "c1"; return undefined; });
            order = "";
            set(false);
            check(order === "t1t2c1", "topo order: got '" + order + "'");
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Circular dependency test
# ──────────────────────────────────────────────

def test_circular_dependency():
    """Circular dependency should throw."""
    r = run_ts('''
        let threw = false;
        try {
            createRoot((_d: any) => {
                const [d, set] = createSignal(1);
                let i = 2;
                const f1 = createMemo(() => d());
                const f2 = createMemo(() => f1());
                const f3 = createMemo(() => f2());
                const _x = createMemo(() => { f3(); set(i++); return undefined; });
            });
        } catch (e) {
            threw = true;
        }
        check(threw, "circular dependency should throw");
        console.log("PASS");
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout


# ──────────────────────────────────────────────
# Effect tests
# ──────────────────────────────────────────────

def test_effect_basic():
    """Effects should run when dependencies change."""
    r = run_ts('''
        let effectVal = -1;
        let setS: any;
        createRoot((_d: any) => {
            const [s, _setS] = createSignal(0);
            setS = _setS;
            createEffect(() => { effectVal = s(); return undefined; });
        });
        // Effects run at end of createRoot's update cycle
        check(effectVal === 0, "effect initial: " + effectVal);
        setS(42);
        check(effectVal === 42, "effect updated: " + effectVal);
        console.log("PASS");
    ''')
    assert r.returncode == 0, f"stderr={r.stderr}"
    assert "PASS" in r.stdout


def test_ensures_new_deps_updated_before_dependee():
    """New dependencies are updated before the dependee reads them."""
    r = run_ts('''
        createRoot((_d: any) => {
            let order = "";
            const [a, setA] = createSignal(0);
            const b = createMemo(() => { order += "b"; return a() + 1; });
            const c = createMemo((): number => {
                order += "c";
                const val = b();
                if (val) return val;
                return e();
            });
            const d = createMemo(() => a());
            const e = createMemo(() => { order += "d"; return d() + 10; });
            check(order === "bcd", "init order: " + order);
            order = "";
            setA(-1);
            check(order === "bcd", "switch order: " + order);
            check(c() === 9, "c after switch: " + c());
            order = "";
            setA(0);
            check(order === "bcd", "switch back: " + order);
            check(c() === 1, "c after switch back: " + c());
            console.log("PASS");
        });
    ''')
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "PASS" in r.stdout
