
import { signal, computed, effect, flushEffects, untracked } from '../app/src/index';

interface TestResult {
  name: string;
  pass: boolean;
  detail?: string;
}

const results: TestResult[] = [];

function test(name: string, fn: () => void): void {
  try {
    fn();
    results.push({ name, pass: true });
  } catch (e: any) {
    results.push({ name, pass: false, detail: String(e?.message || e) });
  }
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

// ============================================================
// Test 1: Basic signal read/write
// ============================================================
test('basic_signal', () => {
  const s = signal(0);
  assert(s() === 0, `Expected 0, got ${s()}`);
  s.set(5);
  assert(s() === 5, `Expected 5 after set, got ${s()}`);
  s.update(v => v + 3);
  assert(s() === 8, `Expected 8 after update, got ${s()}`);
});

// ============================================================
// Test 2: Basic computed derivation
// ============================================================
test('basic_computed', () => {
  const a = signal(3);
  const b = computed(() => a() * 2);
  assert(b() === 6, `Expected 6, got ${b()}`);
  a.set(10);
  assert(b() === 20, `Expected 20, got ${b()}`);
});

// ============================================================
// Test 3: Diamond dependency — glitch-free guarantee
// D depends on B and C, both depend on A.
// Changing A must cause D to recompute exactly once.
// ============================================================
test('diamond_glitch_free', () => {
  const a = signal(0);
  const b = computed(() => a() + 1);
  const c = computed(() => a() * 2);
  let dComputeCount = 0;
  const d = computed(() => {
    dComputeCount++;
    return b() + c();
  });

  // Initial read
  assert(d() === 1, `Initial: expected 1, got ${d()}`); // (0+1) + (0*2) = 1
  dComputeCount = 0;

  a.set(5);
  const result = d();
  assert(result === 16, `After set(5): expected 16, got ${result}`); // (5+1) + (5*2) = 16
  assert(dComputeCount === 1, `D should compute exactly once, computed ${dComputeCount} times`);
});

// ============================================================
// Test 4: Deep diamond with 4 layers
// ============================================================
test('deep_diamond', () => {
  const a = signal(0);
  const b = computed(() => a() + 1);
  const c = computed(() => a() + 2);
  const d = computed(() => b() + 10);
  const e = computed(() => c() + 20);
  let fComputeCount = 0;
  const f = computed(() => {
    fComputeCount++;
    return d() + e();
  });

  assert(f() === 33, `Initial: expected 33, got ${f()}`); // (0+1+10) + (0+2+20) = 33
  fComputeCount = 0;

  a.set(1);
  const result = f();
  assert(result === 35, `After set(1): expected 35, got ${result}`);
  assert(fComputeCount === 1, `F should compute exactly once, computed ${fComputeCount} times`);
});

// ============================================================
// Test 5: Dynamic dependency tracking (conditional)
// When showCount is false, count should NOT be a dependency.
// ============================================================
test('dynamic_deps_conditional', () => {
  const showCount = signal(true);
  const count = signal(0);
  let computeCount = 0;
  const display = computed(() => {
    computeCount++;
    return showCount() ? `Count: ${count()}` : 'hidden';
  });

  assert(display() === 'Count: 0', 'Initial display');
  computeCount = 0;

  // count is a dependency when showCount is true
  count.set(5);
  assert(display() === 'Count: 5', 'After count=5');
  assert(computeCount === 1, 'Should recompute when tracked dep changes');
  computeCount = 0;

  // Switch off: count should no longer be tracked
  showCount.set(false);
  assert(display() === 'hidden', 'After showCount=false');
  computeCount = 0;

  // Changing count should NOT trigger recomputation
  count.set(10);
  const val = display();
  assert(val === 'hidden', `Expected 'hidden', got '${val}'`);
  assert(computeCount === 0, `Should NOT recompute when untracked dep changes, but computed ${computeCount} times`);
});

// ============================================================
// Test 6: Computed equality cutoff
// When computed output doesn't change, downstream should not recompute.
// ============================================================
test('computed_equality_cutoff', () => {
  const a = signal(0);
  const parity = computed(() => a() % 2 === 0 ? 'even' : 'odd');
  let downstreamCount = 0;
  const downstream = computed(() => {
    downstreamCount++;
    return `Result: ${parity()}`;
  });

  assert(downstream() === 'Result: even', 'Initial');
  downstreamCount = 0;

  a.set(2); // still even — parity value unchanged
  downstream();
  assert(downstreamCount === 0, `Downstream should NOT recompute when parity unchanged, but computed ${downstreamCount} times`);

  a.set(3); // now odd
  assert(downstream() === 'Result: odd', 'After set(3)');
});

// ============================================================
// Test 7: Computed equality cutoff with custom equal
// ============================================================
test('computed_custom_equality_cutoff', () => {
  const a = signal(1);
  let absCount = 0;
  const absVal = computed(() => {
    absCount++;
    return Math.abs(a());
  });
  let downCount = 0;
  const down = computed(() => {
    downCount++;
    return absVal() * 10;
  });

  assert(down() === 10, 'Initial');
  absCount = 0;
  downCount = 0;

  a.set(-1); // absVal recomputes to 1 (same value), downstream should NOT recompute
  down();
  assert(absCount === 1, `absVal should recompute once, computed ${absCount} times`);
  assert(downCount === 0, `Downstream should NOT recompute, computed ${downCount} times`);
});

// ============================================================
// Test 8: Cycle detection
// ============================================================
test('cycle_detection', () => {
  let c: any;
  c = computed(() => c() + 1);
  let error: any = null;
  try {
    c();
  } catch (e: any) {
    error = e;
  }
  assert(error !== null, 'Should throw on cyclic computed');
  assert(!(error instanceof RangeError), 'Should throw clean error, not stack overflow');

  // State should be recoverable after cycle error
  const a = signal(1);
  const b = computed(() => a() * 2);
  assert(b() === 2, 'State should be clean after cycle error');
  a.set(5);
  assert(b() === 10, 'Reactivity should work after cycle error');
});

// ============================================================
// Test 9: Write guard — no signal writes inside computed
// ============================================================
test('write_guard_computed', () => {
  const a = signal(0);
  const b = signal(0);
  const c = computed(() => {
    b.set(a());
    return a();
  });
  let error: any = null;
  try {
    c();
  } catch (e: any) {
    error = e;
  }
  assert(error !== null, 'Should throw when writing to signal inside computed');
});

// ============================================================
// Test 10: Write allowed inside effect
// ============================================================
test('write_in_effect_allowed', () => {
  const a = signal(0);
  const b = signal(0);
  effect(() => {
    b.set(a() + 1);
  });
  flushEffects();
  assert(b() === 1, `Expected b=1, got ${b()}`);
  a.set(5);
  flushEffects();
  assert(b() === 6, `Expected b=6, got ${b()}`);
});

// ============================================================
// Test 11: Effect deduplication with diamond deps
// ============================================================
test('effect_diamond_dedup', () => {
  const a = signal(0);
  const b = computed(() => a() + 1);
  const c = computed(() => a() * 2);
  let effectRunCount = 0;
  effect(() => {
    effectRunCount++;
    b();
    c();
  });
  flushEffects();
  assert(effectRunCount === 1, 'Initial effect run');
  effectRunCount = 0;

  a.set(5);
  flushEffects();
  assert(effectRunCount === 1, `Effect with diamond deps should run once, ran ${effectRunCount} times`);
});

// ============================================================
// Test 12: Effect with overlapping transitive and direct deps
// (Issue #68308: effect reads both computed and its source signal)
// ============================================================
test('effect_overlapping_deps', () => {
  const count = signal(0);
  const doubled = computed(() => count() * 2);
  let effectRunCount = 0;
  let lastValues: number[] = [];
  effect(() => {
    effectRunCount++;
    lastValues = [doubled(), count()];
  });
  flushEffects();
  assert(effectRunCount === 1, 'Initial run');
  assert(lastValues[0] === 0 && lastValues[1] === 0, 'Initial values');
  effectRunCount = 0;

  count.set(3);
  flushEffects();
  assert(effectRunCount === 1, `Effect with overlapping deps should run once, ran ${effectRunCount} times`);
  assert(lastValues[0] === 6 && lastValues[1] === 3, `Expected [6,3], got [${lastValues}]`);
});

// ============================================================
// Test 13: Effect cleanup
// ============================================================
test('effect_cleanup', () => {
  let cleanupCount = 0;
  const a = signal(0);
  effect((onCleanup) => {
    a();
    onCleanup(() => { cleanupCount++; });
  });
  flushEffects();
  assert(cleanupCount === 0, 'No cleanup on first run');

  a.set(1);
  flushEffects();
  assert(cleanupCount === 1, `Expected cleanup=1 after second run, got ${cleanupCount}`);

  a.set(2);
  flushEffects();
  assert(cleanupCount === 2, `Expected cleanup=2 after third run, got ${cleanupCount}`);
});

// ============================================================
// Test 14: Untracked reads
// ============================================================
test('untracked_reads', () => {
  const a = signal(0);
  const b = signal(10);
  let computeCount = 0;
  const c = computed(() => {
    computeCount++;
    return a() + untracked(() => b());
  });

  assert(c() === 10, `Initial: expected 10, got ${c()}`);
  computeCount = 0;

  b.set(20);
  c();
  assert(computeCount === 0, `Should NOT recompute when untracked dep changes, computed ${computeCount} times`);

  a.set(1);
  const val = c();
  assert(val === 21, `Expected 21, got ${val}`);
  assert(computeCount === 1, 'Should recompute once for tracked dep change');
});

// ============================================================
// Test 15: Effect destroy
// ============================================================
test('effect_destroy', () => {
  const a = signal(0);
  let effectRunCount = 0;
  const ref = effect(() => {
    effectRunCount++;
    a();
  });
  flushEffects();
  assert(effectRunCount === 1, 'Initial run');
  effectRunCount = 0;

  ref.destroy();
  a.set(5);
  flushEffects();
  assert(effectRunCount === 0, `After destroy, effect should not run, ran ${effectRunCount} times`);
});

// ============================================================
// Test 16: Signal equality prevents notification
// ============================================================
test('signal_equality_no_notification', () => {
  const a = signal(5);
  let computeCount = 0;
  const b = computed(() => {
    computeCount++;
    return a() * 2;
  });
  assert(b() === 10, 'Initial');
  computeCount = 0;

  a.set(5); // Same value — should not trigger
  b();
  assert(computeCount === 0, `Should NOT recompute when signal set to same value, computed ${computeCount} times`);
});

// ============================================================
// Test 17: Complex reactive graph combining features
// ============================================================
test('complex_reactive_graph', () => {
  const firstName = signal('John');
  const lastName = signal('Doe');
  const showFullName = signal(true);

  let displayComputeCount = 0;
  const displayName = computed(() => {
    displayComputeCount++;
    if (showFullName()) {
      return `${firstName()} ${lastName()}`;
    }
    return firstName();
  });

  let effectValues: string[] = [];
  effect(() => {
    effectValues.push(displayName());
  });
  flushEffects();
  assert(effectValues.length === 1, 'Effect ran once initially');
  assert(effectValues[0] === 'John Doe', 'Initial display');
  displayComputeCount = 0;

  // Change lastName — should trigger recomputation and effect
  lastName.set('Smith');
  flushEffects();
  assert(effectValues[effectValues.length - 1] === 'John Smith', 'After lastName change');
  assert(displayComputeCount === 1, `Display should recompute once, computed ${displayComputeCount} times`);
  displayComputeCount = 0;

  // Switch to first-name-only mode (dynamic dep removal)
  showFullName.set(false);
  flushEffects();
  assert(effectValues[effectValues.length - 1] === 'John', 'After switching to short mode');
  displayComputeCount = 0;

  // Changing lastName should NOT trigger anything (no longer tracked)
  lastName.set('Jones');
  flushEffects();
  assert(displayComputeCount === 0, `Display should NOT recompute in short mode, computed ${displayComputeCount} times`);
});

// ============================================================
// Output results
// ============================================================
console.log(JSON.stringify(results));
