package engine

import (
	"context"
	"fmt"
	"log"
	"sort"
	"sync"
	"time"
)

type Reconciler struct {
	Graph           *Graph
	ConvergeTimeout time.Duration
	MaxRetries      int
	RetryDelay      time.Duration
	Apply           bool
}

func (r *Reconciler) Run(ctx context.Context) error {
	// 1. Detect cycles in the dependency graph.
	if err := r.detectCycles(); err != nil {
		return err
	}

	// 2. Compute topological order.
	sorted, err := r.topoSort()
	if err != nil {
		return err
	}

	// 3. Per-resource bookkeeping: event channel, refresh flag, ready signal.
	type refreshState struct {
		mu   sync.Mutex
		flag bool
	}

	events := make(chan string, len(r.Graph.Resources())*4+4)
	watchReady := make(map[string]chan struct{})
	refreshes := make(map[string]*refreshState)

	for name, res := range r.Graph.Resources() {
		readyCh := make(chan struct{})
		watchReady[name] = readyCh
		rs := &refreshState{}
		refreshes[name] = rs

		var readyOnce sync.Once
		nameLocal := name

		init := &Init{
			Running: func() error {
				readyOnce.Do(func() { close(readyCh) })
				return nil
			},
			Event: func() error {
				select {
				case events <- nameLocal:
				default: // coalesce
				}
				return nil
			},
			Refresh: func() bool {
				rs.mu.Lock()
				defer rs.mu.Unlock()
				f := rs.flag
				rs.flag = false
				return f
			},
			Logf: func(format string, v ...interface{}) {
				log.Printf("[%s] "+format, append([]interface{}{nameLocal}, v...)...)
			},
			Debug: false,
		}

		if err := res.Init(init); err != nil {
			return fmt.Errorf("init resource %s: %w", name, err)
		}
	}

	// 4. Start Watch goroutines.
	watchCtx, watchCancel := context.WithCancel(ctx)
	defer watchCancel()

	var watchWg sync.WaitGroup
	for name, res := range r.Graph.Resources() {
		watchWg.Add(1)
		go func(n string, re Res) {
			defer watchWg.Done()
			_ = re.Watch(watchCtx)
		}(name, res)
	}

	// Wait for all watches to signal readiness.
	for name, ch := range watchReady {
		select {
		case <-ch:
		case <-ctx.Done():
			watchCancel()
			watchWg.Wait()
			r.cleanupAll()
			return fmt.Errorf("timeout waiting for watch on %s: %w", name, ctx.Err())
		}
	}

	// 5. Reconciliation state.
	type resStatus struct {
		needsCheck bool
		converged  bool
		retries    int
	}

	status := make(map[string]*resStatus)
	for _, name := range sorted {
		status[name] = &resStatus{needsCheck: true}
	}

	convergeTimer := time.NewTimer(r.ConvergeTimeout)
	if !convergeTimer.Stop() {
		select {
		case <-convergeTimer.C:
		default:
		}
	}
	defer convergeTimer.Stop()
	converging := false

	stopAndDrainTimer := func() {
		if !convergeTimer.Stop() {
			select {
			case <-convergeTimer.C:
			default:
			}
		}
	}

	shutdown := func() {
		watchCancel()
		watchWg.Wait()
		r.cleanupAll()
	}

	// 6. Main reconciliation loop.
	for {
		// Find resources ready to check: needsCheck=true and all deps converged.
		var ready []string
		for _, name := range sorted {
			s := status[name]
			if !s.needsCheck {
				continue
			}
			depsOK := true
			for _, dep := range r.Graph.Dependencies(name) {
				if !status[dep].converged {
					depsOK = false
					break
				}
			}
			if depsOK {
				ready = append(ready, name)
			}
		}

		if len(ready) > 0 {
			if converging {
				stopAndDrainTimer()
				converging = false
			}

			// Run CheckApply in parallel for ready resources.
			type checkResult struct {
				name    string
				checkOK bool
				err     error
			}

			resultsCh := make(chan checkResult, len(ready))
			for _, name := range ready {
				go func(n string) {
					res := r.Graph.Resources()[n]
					ok, err := res.CheckApply(ctx, r.Apply)
					resultsCh <- checkResult{name: n, checkOK: ok, err: err}
				}(name)
			}

			// Collect and process results (sequentially for safe status access).
			var fatalErr error
			for range ready {
				result := <-resultsCh
				s := status[result.name]
				s.needsCheck = false

				if result.err != nil {
					s.retries++
					if s.retries > r.MaxRetries {
						fatalErr = fmt.Errorf("resource %s failed after %d retries: %w",
							result.name, r.MaxRetries, result.err)
						continue
					}
					// Schedule retry with exponential backoff.
					go func(name string, retries int) {
						delay := r.RetryDelay * time.Duration(1<<uint(retries-1))
						select {
						case <-time.After(delay):
							select {
							case events <- name:
							default:
							}
						case <-ctx.Done():
						}
					}(result.name, s.retries)
					continue
				}

				s.retries = 0
				s.converged = true

				if !result.checkOK {
					// State was wrong, changes were applied.
					// Propagate refresh to notify-edge targets.
					for _, target := range r.Graph.NotifyTargets(result.name) {
						rs := refreshes[target]
						rs.mu.Lock()
						rs.flag = true
						rs.mu.Unlock()
						status[target].needsCheck = true
						status[target].converged = false
					}
				}
			}

			if fatalErr != nil {
				shutdown()
				return fatalErr
			}

			continue // loop back to find more ready resources
		}

		// No resources are ready. Either all converged or waiting for deps/events.
		allDone := true
		for _, s := range status {
			if s.needsCheck || !s.converged {
				allDone = false
				break
			}
		}

		if allDone {
			if !converging {
				convergeTimer.Reset(r.ConvergeTimeout)
				converging = true
			}

			select {
			case name := <-events:
				converging = false
				stopAndDrainTimer()
				status[name].needsCheck = true
				status[name].converged = false
			case <-convergeTimer.C:
				// Stable convergence achieved.
				converging = false
				shutdown()
				return nil
			case <-ctx.Done():
				shutdown()
				return nil
			}
		} else {
			// Not all converged, waiting for events or dependencies.
			select {
			case name := <-events:
				status[name].needsCheck = true
				status[name].converged = false
			case <-ctx.Done():
				shutdown()
				return nil
			}
		}
	}
}

// detectCycles performs DFS-based cycle detection on the directed graph.
func (r *Reconciler) detectCycles() error {
	const (
		white = iota // not visited
		gray         // in current DFS path
		black        // fully explored
	)

	color := make(map[string]int)
	for name := range r.Graph.Resources() {
		color[name] = white
	}

	var dfs func(name string) error
	dfs = func(name string) error {
		color[name] = gray
		for _, dep := range r.Graph.Dependents(name) {
			switch color[dep] {
			case gray:
				return fmt.Errorf("cycle detected: edge %s -> %s creates a cycle", name, dep)
			case white:
				if err := dfs(dep); err != nil {
					return err
				}
			}
		}
		color[name] = black
		return nil
	}

	for name := range r.Graph.Resources() {
		if color[name] == white {
			if err := dfs(name); err != nil {
				return err
			}
		}
	}
	return nil
}

// topoSort returns resources in topological order using Kahn's algorithm.
func (r *Reconciler) topoSort() ([]string, error) {
	inDegree := make(map[string]int)
	for name := range r.Graph.Resources() {
		inDegree[name] = 0
	}
	for _, e := range r.Graph.Edges() {
		inDegree[e.To]++
	}

	var queue []string
	for name, deg := range inDegree {
		if deg == 0 {
			queue = append(queue, name)
		}
	}
	sort.Strings(queue) // deterministic ordering

	var sorted []string
	for len(queue) > 0 {
		name := queue[0]
		queue = queue[1:]
		sorted = append(sorted, name)

		for _, dep := range r.Graph.Dependents(name) {
			inDegree[dep]--
			if inDegree[dep] == 0 {
				queue = append(queue, dep)
			}
		}
		sort.Strings(queue)
	}

	if len(sorted) != len(r.Graph.Resources()) {
		return nil, fmt.Errorf("graph has cycles (topological sort incomplete)")
	}
	return sorted, nil
}

// cleanupAll calls Cleanup on every resource in the graph.
func (r *Reconciler) cleanupAll() {
	for _, res := range r.Graph.Resources() {
		res.Cleanup()
	}
}
