package engine

import (
	"context"
	"sync"
	"sync/atomic"
)

// MockRes is a configurable mock resource for testing. Set the Fn fields
// to control behavior; leave nil for sensible defaults.
type MockRes struct {
	ResName string
	ResKind string

	mu   sync.Mutex
	init *Init

	// Behavior overrides. If nil, defaults are used.
	WatchFn      func(ctx context.Context, init *Init) error
	CheckApplyFn func(ctx context.Context, apply bool, init *Init) (bool, error)
	InitFn       func(init *Init) error
	CleanupFn    func() error

	// Counters for observation (use sync/atomic to read).
	InitCount      int32
	WatchCount     int32
	CheckCallCount int32
	CleanupCount   int32
}

func (m *MockRes) Name() string { return m.ResName }
func (m *MockRes) Kind() string { return m.ResKind }

func (m *MockRes) Init(init *Init) error {
	atomic.AddInt32(&m.InitCount, 1)
	m.mu.Lock()
	m.init = init
	m.mu.Unlock()
	if m.InitFn != nil {
		return m.InitFn(init)
	}
	return nil
}

func (m *MockRes) Cleanup() error {
	atomic.AddInt32(&m.CleanupCount, 1)
	if m.CleanupFn != nil {
		return m.CleanupFn()
	}
	return nil
}

func (m *MockRes) Watch(ctx context.Context) error {
	atomic.AddInt32(&m.WatchCount, 1)
	m.mu.Lock()
	init := m.init
	m.mu.Unlock()
	if m.WatchFn != nil {
		return m.WatchFn(ctx, init)
	}
	// Default: signal running, send one initial event, wait for cancel.
	if err := init.Running(); err != nil {
		return err
	}
	if err := init.Event(); err != nil {
		return err
	}
	<-ctx.Done()
	return nil
}

func (m *MockRes) CheckApply(ctx context.Context, apply bool) (bool, error) {
	atomic.AddInt32(&m.CheckCallCount, 1)
	m.mu.Lock()
	init := m.init
	m.mu.Unlock()
	if m.CheckApplyFn != nil {
		return m.CheckApplyFn(ctx, apply, init)
	}
	// Default: state is correct, no changes needed.
	return true, nil
}
