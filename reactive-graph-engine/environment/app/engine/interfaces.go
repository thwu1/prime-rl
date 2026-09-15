
package engine

import "context"

// Res is the interface that all resources must implement. It follows the
// mgmt-style resource API with event-driven Watch and idempotent CheckApply.
type Res interface {
	// Name returns the unique name of this resource instance.
	Name() string

	// Kind returns the resource type (e.g., "file", "svc").
	Kind() string

	// Init initializes the resource with callbacks for communicating
	// with the engine. It is called before Watch or CheckApply.
	Init(init *Init) error

	// Cleanup releases any resources held by this resource.
	// Called after Watch has exited during shutdown.
	Cleanup() error

	// Watch monitors for external state changes and notifies the engine
	// via init.Event(). It must:
	//   1. Set up its monitoring mechanism
	//   2. Call init.Running() exactly once when ready
	//   3. Call init.Event() whenever state may have changed
	//   4. Block until ctx is cancelled, then return
	Watch(ctx context.Context) error

	// CheckApply checks the current state and optionally applies fixes.
	//
	// Return values:
	//   (true, nil)  — state is correct, no changes needed
	//   (false, nil) — state was wrong; if apply=true, changes were applied
	//   (false, err) — an error occurred during check or apply
	//
	// When apply=false (noop mode), no changes should be made to the system.
	CheckApply(ctx context.Context, apply bool) (checkOK bool, err error)
}

// Init provides callbacks for a resource to communicate with the engine.
// The engine creates this struct and passes it to Res.Init().
type Init struct {
	// Running must be called exactly once from Watch when the watch
	// loop is set up and ready to detect state changes.
	Running func() error

	// Event notifies the engine that the resource's state may have changed.
	// Called from Watch. This is non-blocking; duplicate events are coalesced.
	Event func() error

	// Refresh returns true if a refresh notification was received from
	// an upstream resource via a notify-edge. The flag is cleared after
	// reading. Called from within CheckApply.
	Refresh func() bool

	// Logf logs a message associated with this resource.
	Logf func(format string, v ...interface{})

	// Debug indicates whether debug logging is enabled.
	Debug bool
}
