#!/usr/bin/env python3
"""
Discrete-event simulator for load-balancing with stale cached data
and stochastic fairness queuing (SFQ).

Demonstrates:
1. Herding effect: BEST strategy degrades under stale data as all clients
   converge on the same "best" server from their stale snapshot.
2. Power of two random choices: BEST_OF_2 avoids herding by introducing
   randomness, remaining robust to staleness.
3. SFQ isolation: work-conserving round-robin across hash-assigned queues
   isolates non-noisy customers from a noisy neighbor.
"""


import json
import heapq
import random


def load_config():
    with open("/app/config.json") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Discrete-event simulation engine
# ---------------------------------------------------------------------------

class EventLoop:
    """Heap-based discrete-event simulation engine."""

    def __init__(self):
        self._heap = []
        self._counter = 0
        self.time = 0.0

    def schedule(self, time, callback, *args):
        self._counter += 1
        heapq.heappush(self._heap, (time, self._counter, callback, args))

    def run(self, until):
        while self._heap:
            t, _, cb, args = heapq.heappop(self._heap)
            if t > until:
                break
            self.time = t
            cb(*args)


# ---------------------------------------------------------------------------
# Part 1: Load-balancing simulation with stale data
# ---------------------------------------------------------------------------

class LBServer:
    """Models a single backend server with a FIFO request queue."""

    def __init__(self, sid, service_mean, rng, el):
        self.sid = sid
        self.service_mean = service_mean
        self.rng = rng
        self.el = el
        self.queue = []
        self.current = None

    @property
    def queue_depth(self):
        return len(self.queue) + (1 if self.current is not None else 0)

    def enqueue(self, arrival_time, on_complete):
        self.queue.append((arrival_time, on_complete))
        if self.current is None:
            self._start_next()

    def _start_next(self):
        if not self.queue:
            self.current = None
            return
        self.current = self.queue.pop(0)
        svc_time = self.rng.expovariate(1.0 / self.service_mean)
        self.el.schedule(self.el.time + svc_time, self._complete)

    def _complete(self):
        arrival_time, on_complete = self.current
        latency = self.el.time - arrival_time
        on_complete(latency)
        self.current = None
        self._start_next()


STRATEGY_INDEX = {"RANDOM": 0, "BEST": 1, "BEST_OF_2": 2, "BEST_OF_3": 3}


class LoadBalancingSim:
    """Simulates load balancing with cached/stale server load information."""

    def __init__(self, config, strategy, staleness):
        lb = config["load_balancing"]
        seed = lb["seed"] * 10000 + STRATEGY_INDEX[strategy] * 1000 + staleness
        self.rng = random.Random(seed)
        self.el = EventLoop()
        self.strategy = strategy
        self.staleness = staleness
        self.num_servers = lb["num_servers"]
        self.num_clients = lb["num_clients"]
        self.arrival_rate = lb["base_arrival_rate"]
        self.service_mean = lb["service_time_mean"]
        self.duration = lb["simulation_duration"]

        self.servers = [
            LBServer(i, self.service_mean, self.rng, self.el)
            for i in range(self.num_servers)
        ]
        # Each client has a cached view of server queue depths
        self.client_caches = [
            [0] * self.num_servers for _ in range(self.num_clients)
        ]

        self.latencies = []
        self.depth_samples = []

    def _get_loads(self, client_id):
        """Return the load view for this client (live or cached)."""
        if self.staleness == 0:
            return [s.queue_depth for s in self.servers]
        return self.client_caches[client_id]

    def _pick_server(self, client_id):
        """Select a server using the configured strategy."""
        loads = self._get_loads(client_id)
        if self.strategy == "RANDOM":
            return self.rng.randrange(self.num_servers)
        elif self.strategy == "BEST":
            min_load = min(loads)
            candidates = [i for i, ld in enumerate(loads) if ld == min_load]
            return self.rng.choice(candidates)
        else:
            # BEST_OF_K
            k = int(self.strategy.split("_")[-1])
            k = min(k, self.num_servers)
            choices = self.rng.sample(range(self.num_servers), k)
            return min(choices, key=lambda i: loads[i])

    def _refresh_caches(self):
        """Synchronized cache refresh: all clients see the same snapshot."""
        depths = [s.queue_depth for s in self.servers]
        for cid in range(self.num_clients):
            self.client_caches[cid] = depths[:]
        if self.staleness > 0:
            self.el.schedule(
                self.el.time + self.staleness, self._refresh_caches
            )

    def _request_arrive(self, client_id):
        """Handle a request arrival from a client."""
        sid = self._pick_server(client_id)
        arrival_time = self.el.time
        self.servers[sid].enqueue(
            arrival_time, lambda lat: self.latencies.append(lat)
        )
        # Schedule next request (Poisson process)
        dt = self.rng.expovariate(self.arrival_rate)
        self.el.schedule(self.el.time + dt, self._request_arrive, client_id)

    def _sample_queues(self):
        """Periodically sample queue depths for statistics."""
        for s in self.servers:
            self.depth_samples.append(s.queue_depth)
        self.el.schedule(self.el.time + 10.0, self._sample_queues)

    def run(self):
        # Initialize: refresh caches, start request generators, start sampling
        self._refresh_caches()
        for cid in range(self.num_clients):
            start_t = self.rng.uniform(0, 1.0)
            self.el.schedule(start_t, self._request_arrive, cid)
        self.el.schedule(0.0, self._sample_queues)
        self.el.run(self.duration)
        return self._compute_stats()

    def _compute_stats(self):
        if not self.latencies:
            return {
                "mean_latency": 0,
                "p50_latency": 0,
                "p95_latency": 0,
                "p99_latency": 0,
                "mean_queue_depth": 0,
                "max_queue_depth": 0,
            }
        self.latencies.sort()
        n = len(self.latencies)
        return {
            "mean_latency": sum(self.latencies) / n,
            "p50_latency": self.latencies[int(n * 0.50)],
            "p95_latency": self.latencies[int(n * 0.95)],
            "p99_latency": self.latencies[min(int(n * 0.99), n - 1)],
            "mean_queue_depth": (
                sum(self.depth_samples) / len(self.depth_samples)
                if self.depth_samples
                else 0
            ),
            "max_queue_depth": (
                max(self.depth_samples) if self.depth_samples else 0
            ),
        }


# ---------------------------------------------------------------------------
# Part 2: Stochastic Fairness Queuing (SFQ)
# ---------------------------------------------------------------------------

class SFQSim:
    """
    Simulates a single service point with either FCFS or SFQ two-choice
    queue assignment.  Work-conserving round-robin across queues.
    """

    def __init__(self, config, mode):
        sfq = config["sfq"]
        # Deterministic, mode-dependent seed
        mode_offset = 0 if mode == "fcfs" else 7
        self.rng = random.Random(sfq["seed"] * 100 + mode_offset)
        self.el = EventLoop()
        self.mode = mode
        self.num_queues = 1 if mode == "fcfs" else sfq["num_queues"]
        self.num_customers = sfq["num_customers"]
        self.noisy_id = sfq["noisy_customer_id"]
        self.noisy_mult = sfq["noisy_multiplier"]
        self.base_rate = sfq["base_customer_rate"]
        self.service_mean = sfq["service_time_mean"]
        self.duration = sfq["simulation_duration"]
        self.perturb_interval = sfq["perturb_interval"]

        self.queues = [[] for _ in range(self.num_queues)]
        self.customer_latencies = {c: [] for c in range(self.num_customers)}
        self.server_busy = False
        self.current_queue_idx = 0

        # Hash mappings: each customer -> 2 queues
        self.hash1 = {}
        self.hash2 = {}
        self._perturb_hash()

    def _perturb_hash(self):
        """Reassign customer -> queue mappings."""
        for cid in range(self.num_customers):
            q1 = self.rng.randrange(self.num_queues)
            remaining = [q for q in range(self.num_queues) if q != q1]
            q2 = self.rng.choice(remaining) if remaining else q1
            self.hash1[cid] = q1
            self.hash2[cid] = q2
        if self.mode != "fcfs":
            self.el.schedule(
                self.el.time + self.perturb_interval, self._perturb_hash
            )

    def _get_queue(self, cid):
        """Determine which queue a customer's request goes to."""
        if self.mode == "fcfs":
            return 0
        q1 = self.hash1[cid]
        q2 = self.hash2[cid]
        return q1 if len(self.queues[q1]) <= len(self.queues[q2]) else q2

    def _request_arrive(self, cid):
        """Handle a customer request arrival."""
        qid = self._get_queue(cid)
        self.queues[qid].append((self.el.time, cid))
        if not self.server_busy:
            self._serve_next()
        # Schedule next request
        rate = self.base_rate * (
            self.noisy_mult if cid == self.noisy_id else 1.0
        )
        dt = self.rng.expovariate(rate)
        self.el.schedule(self.el.time + dt, self._request_arrive, cid)

    def _serve_next(self):
        """Work-conserving round-robin: find next non-empty queue and serve."""
        for _ in range(self.num_queues):
            q = self.queues[self.current_queue_idx]
            self.current_queue_idx = (
                (self.current_queue_idx + 1) % self.num_queues
            )
            if q:
                arrival_time, cid = q.pop(0)
                self.server_busy = True
                svc = self.rng.expovariate(1.0 / self.service_mean)
                self.el.schedule(
                    self.el.time + svc,
                    self._complete_service,
                    cid,
                    arrival_time,
                )
                return
        self.server_busy = False

    def _complete_service(self, cid, arrival_time):
        """Handle service completion: record latency, serve next."""
        latency = self.el.time - arrival_time
        self.customer_latencies[cid].append(latency)
        self._serve_next()

    def run(self):
        # Start request generators for each customer
        for cid in range(self.num_customers):
            self.el.schedule(
                self.rng.uniform(0, 0.5), self._request_arrive, cid
            )
        self.el.run(self.duration)
        return self._compute_stats()

    def _compute_stats(self):
        p99s = []
        for cid in range(self.num_customers):
            lats = sorted(self.customer_latencies.get(cid, [0.0]))
            if lats:
                idx = min(int(len(lats) * 0.99), len(lats) - 1)
                p99s.append(lats[idx])
            else:
                p99s.append(0.0)
        return {"per_customer_p99": p99s}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    results = {"load_balancing": [], "sfq": {}}

    lb_cfg = config["load_balancing"]
    for strategy in lb_cfg["strategies"]:
        for staleness in lb_cfg["staleness_intervals"]:
            sim = LoadBalancingSim(config, strategy, staleness)
            stats = sim.run()
            results["load_balancing"].append(
                {"strategy": strategy, "staleness": staleness, **stats}
            )

    for mode in ["fcfs", "sfq_two_choice"]:
        sim = SFQSim(config, mode)
        results["sfq"][mode] = sim.run()

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)


if __name__ == "__main__":
    main()
