
package engine

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// TestCycleDetection verifies the engine detects cycles and returns an error.
func TestCycleDetection(t *testing.T) {
	g := NewGraph()
	g.AddResource(&MockRes{ResName: "a", ResKind: "test"})
	g.AddResource(&MockRes{ResName: "b", ResKind: "test"})
	g.AddEdge("a", "b", false)
	g.AddEdge("b", "a", false) // creates a cycle

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err == nil {
		t.Fatal("expected error for cycle in graph, got nil")
	}
}

// TestTriangleCycle checks cycle detection with 3 nodes.
func TestTriangleCycle(t *testing.T) {
	g := NewGraph()
	g.AddResource(&MockRes{ResName: "a", ResKind: "test"})
	g.AddResource(&MockRes{ResName: "b", ResKind: "test"})
	g.AddResource(&MockRes{ResName: "c", ResKind: "test"})
	g.AddEdge("a", "b", false)
	g.AddEdge("b", "c", false)
	g.AddEdge("c", "a", false) // cycle: a -> b -> c -> a

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err == nil {
		t.Fatal("expected error for triangle cycle, got nil")
	}
}

// TestSingleResourceConvergence verifies a single resource converges correctly.
func TestSingleResourceConvergence(t *testing.T) {
	g := NewGraph()
	var checkCount int32
	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			atomic.AddInt32(&checkCount, 1)
			return true, nil
		},
	})

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: 500 * time.Millisecond,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if atomic.LoadInt32(&checkCount) == 0 {
		t.Fatal("CheckApply was never called")
	}
}

// TestLinearDependencyOrder verifies a→b→c executes in correct order.
func TestLinearDependencyOrder(t *testing.T) {
	g := NewGraph()
	var order []string
	var mu sync.Mutex

	for _, name := range []string{"a", "b", "c"} {
		n := name
		g.AddResource(&MockRes{
			ResName: n,
			ResKind: "test",
			CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
				mu.Lock()
				order = append(order, n)
				mu.Unlock()
				return true, nil
			},
		})
	}
	g.AddEdge("a", "b", false) // b depends on a
	g.AddEdge("b", "c", false) // c depends on b

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: 500 * time.Millisecond,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	indexOf := func(s string) int {
		for i, v := range order {
			if v == s {
				return i
			}
		}
		return -1
	}

	ia, ib, ic := indexOf("a"), indexOf("b"), indexOf("c")
	if ia == -1 || ib == -1 || ic == -1 {
		t.Fatalf("missing checks: a=%d b=%d c=%d, order=%v", ia, ib, ic, order)
	}
	if ia >= ib {
		t.Errorf("a (idx %d) must come before b (idx %d)", ia, ib)
	}
	if ib >= ic {
		t.Errorf("b (idx %d) must come before c (idx %d)", ib, ic)
	}
}

// TestParallelExecution verifies independent resources run in parallel.
// Uses a barrier: both a and b signal started then wait for each other.
// If the engine runs them sequentially, this deadlocks → timeout.
func TestParallelExecution(t *testing.T) {
	g := NewGraph()

	aStarted := make(chan struct{})
	bStarted := make(chan struct{})
	var aOnce, bOnce sync.Once
	var cChecked int32

	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			aOnce.Do(func() { close(aStarted) })
			select {
			case <-bStarted:
			case <-ctx.Done():
				return false, ctx.Err()
			}
			return true, nil
		},
	})
	g.AddResource(&MockRes{
		ResName: "b",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			bOnce.Do(func() { close(bStarted) })
			select {
			case <-aStarted:
			case <-ctx.Done():
				return false, ctx.Err()
			}
			return true, nil
		},
	})
	g.AddResource(&MockRes{
		ResName: "c",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			atomic.AddInt32(&cChecked, 1)
			return true, nil
		},
	})

	g.AddEdge("a", "c", false) // c depends on a
	g.AddEdge("b", "c", false) // c depends on b

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("engine failed (a and b may not be running in parallel): %v", err)
	}
	if atomic.LoadInt32(&cChecked) == 0 {
		t.Fatal("c was never checked")
	}
}

// TestRefreshNotification verifies that when resource a makes changes and
// has a notify-edge to b, resource b receives the refresh flag.
func TestRefreshNotification(t *testing.T) {
	g := NewGraph()
	var refreshReceived int32
	var aCheckCount int32

	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			c := atomic.AddInt32(&aCheckCount, 1)
			if c == 1 {
				return false, nil // first check: state was wrong, changes applied
			}
			return true, nil // subsequent: state correct
		},
	})
	g.AddResource(&MockRes{
		ResName: "b",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			if init.Refresh() {
				atomic.AddInt32(&refreshReceived, 1)
			}
			return true, nil
		},
	})

	g.AddEdge("a", "b", true) // notify edge: a notifies b

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if atomic.LoadInt32(&refreshReceived) == 0 {
		t.Fatal("b never received refresh notification from a")
	}
}

// TestNoopMode verifies that when Apply=false, all CheckApply calls
// receive apply=false.
func TestNoopMode(t *testing.T) {
	g := NewGraph()
	var applyValues []bool
	var mu sync.Mutex

	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			mu.Lock()
			applyValues = append(applyValues, apply)
			mu.Unlock()
			return true, nil
		},
	})

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: 500 * time.Millisecond,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           false, // noop mode
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()
	if len(applyValues) == 0 {
		t.Fatal("CheckApply was never called")
	}
	for i, v := range applyValues {
		if v {
			t.Fatalf("CheckApply call %d had apply=true in noop mode", i)
		}
	}
}

// TestEventTriggersRecheck verifies that Watch events trigger additional
// CheckApply calls.
func TestEventTriggersRecheck(t *testing.T) {
	g := NewGraph()
	var checkCount int32

	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		WatchFn: func(ctx context.Context, init *Init) error {
			if err := init.Running(); err != nil {
				return err
			}
			// Initial event
			init.Event()
			// Second event after delay
			select {
			case <-time.After(300 * time.Millisecond):
				init.Event()
			case <-ctx.Done():
				return nil
			}
			<-ctx.Done()
			return nil
		},
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			atomic.AddInt32(&checkCount, 1)
			return true, nil
		},
	})

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	c := atomic.LoadInt32(&checkCount)
	if c < 2 {
		t.Fatalf("expected at least 2 CheckApply calls from 2 Watch events, got %d", c)
	}
}

// TestResourceRetry verifies that a failing CheckApply is retried with
// exponential backoff and eventually succeeds.
func TestResourceRetry(t *testing.T) {
	g := NewGraph()
	var checkCount int32

	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			c := atomic.AddInt32(&checkCount, 1)
			if c <= 2 {
				return false, fmt.Errorf("temporary error #%d", c)
			}
			return true, nil // succeeds on 3rd attempt
		},
	})

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      3,
		RetryDelay:      50 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("expected success after retry, got: %v", err)
	}
	c := atomic.LoadInt32(&checkCount)
	if c < 3 {
		t.Fatalf("expected at least 3 CheckApply calls (2 errors + 1 success), got %d", c)
	}
}

// TestRetryExhaustion verifies that after MaxRetries failures, the engine
// returns an error.
func TestRetryExhaustion(t *testing.T) {
	g := NewGraph()

	g.AddResource(&MockRes{
		ResName: "a",
		ResKind: "test",
		CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
			return false, fmt.Errorf("permanent error")
		},
	})

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: time.Second,
		MaxRetries:      2,
		RetryDelay:      50 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err == nil {
		t.Fatal("expected error after retry exhaustion, got nil")
	}
}

// TestDiamondDependency verifies correct ordering in a diamond-shaped graph:
// a → b, a → c, b → d, c → d
func TestDiamondDependency(t *testing.T) {
	g := NewGraph()
	var order []string
	var mu sync.Mutex

	for _, name := range []string{"a", "b", "c", "d"} {
		n := name
		g.AddResource(&MockRes{
			ResName: n,
			ResKind: "test",
			CheckApplyFn: func(ctx context.Context, apply bool, init *Init) (bool, error) {
				mu.Lock()
				order = append(order, n)
				mu.Unlock()
				return true, nil
			},
		})
	}

	g.AddEdge("a", "b", false)
	g.AddEdge("a", "c", false)
	g.AddEdge("b", "d", false)
	g.AddEdge("c", "d", false)

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: 500 * time.Millisecond,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	indexOf := func(s string) int {
		for i, v := range order {
			if v == s {
				return i
			}
		}
		return -1
	}

	ia, ib, ic, id := indexOf("a"), indexOf("b"), indexOf("c"), indexOf("d")
	if ia == -1 || ib == -1 || ic == -1 || id == -1 {
		t.Fatalf("not all checked: a=%d b=%d c=%d d=%d order=%v", ia, ib, ic, id, order)
	}
	if ia >= ib || ia >= ic {
		t.Errorf("a must come before b and c: a=%d b=%d c=%d", ia, ib, ic)
	}
	if ib >= id || ic >= id {
		t.Errorf("d must come after both b and c: b=%d c=%d d=%d", ib, ic, id)
	}
}

// TestGracefulShutdown verifies Cleanup is called on all resources during
// shutdown.
func TestGracefulShutdown(t *testing.T) {
	g := NewGraph()
	var cleanedUp int32

	for _, name := range []string{"a", "b"} {
		g.AddResource(&MockRes{
			ResName: name,
			ResKind: "test",
			CleanupFn: func() error {
				atomic.AddInt32(&cleanedUp, 1)
				return nil
			},
		})
	}

	rec := &Reconciler{
		Graph:           g,
		ConvergeTimeout: 500 * time.Millisecond,
		MaxRetries:      0,
		RetryDelay:      100 * time.Millisecond,
		Apply:           true,
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := rec.Run(ctx)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	count := atomic.LoadInt32(&cleanedUp)
	if count != 2 {
		t.Fatalf("expected 2 Cleanup calls, got %d", count)
	}
}
