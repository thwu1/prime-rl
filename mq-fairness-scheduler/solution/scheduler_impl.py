"""Reference implementation of the multi-queue fair queuing scheduler.

"""


class TokenBucket:
    def __init__(self, rate, burst):
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_time = 0.0

    def refill(self, current_time):
        elapsed = current_time - self.last_time
        if elapsed > 0:
            self.tokens = min(self.burst, self.tokens + self.rate * elapsed)
            self.last_time = current_time

    def consume(self, amount):
        actual = min(amount, self.tokens)
        self.tokens -= actual
        return actual


class MultiQueueScheduler:
    def __init__(self, num_queues, global_rate, burst_size):
        self.num_queues = num_queues
        self.global_rate = global_rate
        self.token_bucket = TokenBucket(global_rate, burst_size)
        self.flow_queue = {}
        self.flow_weight = {}

    def assign_flow(self, flow_id, queue_id, weight=1.0):
        self.flow_queue[flow_id] = queue_id
        self.flow_weight[flow_id] = weight

    def remove_flow(self, flow_id):
        self.flow_queue.pop(flow_id, None)
        self.flow_weight.pop(flow_id, None)

    def schedule(self, demands, dt, current_time):
        self.token_bucket.refill(current_time)
        budget = self.token_bucket.tokens
        allocations = self._water_fill(demands, budget)
        total = sum(allocations.values())
        self.token_bucket.consume(total)
        return allocations

    def _water_fill(self, demands, budget):
        if not demands or budget <= 0:
            return {fid: 0.0 for fid in demands}

        weights = {fid: self.flow_weight.get(fid, 1.0) for fid in demands}
        allocations = {}
        remaining_budget = budget
        unsatisfied = set(demands.keys())
        remaining_weight = sum(weights[f] for f in unsatisfied)

        changed = True
        while changed and unsatisfied and remaining_budget > 1e-10 and remaining_weight > 1e-10:
            changed = False
            rate_per_weight = remaining_budget / remaining_weight

            for fid in list(unsatisfied):
                fair_share = rate_per_weight * weights[fid]
                demand = demands[fid]

                if demand != float('inf') and demand <= fair_share:
                    allocations[fid] = demand
                    remaining_budget -= demand
                    remaining_weight -= weights[fid]
                    unsatisfied.remove(fid)
                    changed = True

        if unsatisfied and remaining_budget > 1e-10 and remaining_weight > 1e-10:
            for fid in unsatisfied:
                allocations[fid] = remaining_budget * weights[fid] / remaining_weight

        for fid in demands:
            if fid not in allocations:
                allocations[fid] = 0.0

        return allocations


def compute_max_min_fair_rates(global_rate, flow_weights, flow_demands=None):
    if flow_demands is None:
        flow_demands = {}

    allocations = {}
    remaining = global_rate
    remaining_weight = sum(flow_weights.values())

    effective_demands = {}
    for fid in flow_weights:
        d = flow_demands.get(fid)
        effective_demands[fid] = d if d is not None else float('inf')

    items = sorted(flow_weights.keys(),
                   key=lambda f: effective_demands[f] / flow_weights[f]
                   if effective_demands[f] != float('inf') else float('inf'))

    for fid in items:
        w = flow_weights[fid]
        d = effective_demands[fid]
        fair_share = remaining * w / remaining_weight if remaining_weight > 0 else 0

        if d <= fair_share:
            allocations[fid] = d
            remaining -= d
        else:
            allocations[fid] = fair_share
            remaining -= fair_share
        remaining_weight -= w

    return allocations
