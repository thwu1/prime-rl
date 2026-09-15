#!/usr/bin/env python3
"""
Fix the three bugs in /app/scheduler.py:

1. DRR missing quantum increment — deficit never grows, so no packets
   are ever eligible for dequeue (schedule_round always stalls).
2. Rate calculation missing bytes-to-bits conversion (* 8) — transmission
   time is 8x too short, yielding ~160 Mbps instead of 100 Mbps.
3. Flow hash off-by-one — flow_id % (num_queues - 1) causes flows 1
   and 8 to collide in the same queue, breaking isolation and fairness.
"""


with open('/app/scheduler.py') as f:
    code = f.read()

# Bug 1: DRR deficit is never incremented by quantum.
# The DRR algorithm requires adding self.quantum to q.deficit at the
# start of each service opportunity so the queue has credit to transmit.
# Without this line, deficit stays at 0 and the while loop never executes.
code = code.replace(
    '            # Drain packets while deficit permits\n'
    '            while not q.empty and q.deficit >= q.head.size_bytes:',
    '            # Drain packets while deficit permits\n'
    '            q.deficit += self.quantum\n'
    '            while not q.empty and q.deficit >= q.head.size_bytes:'
)

# Bug 2: Transmission time omits the * 8 conversion from bytes to bits.
# self.rate_bps is in bits/sec, but pkt.size_bytes is in bytes.
# Without * 8, the computed tx_ns is 8x too small (link appears 8x faster).
code = code.replace(
    'tx_ns = int(pkt.size_bytes * 1_000_000_000 / self.rate_bps)',
    'tx_ns = int(pkt.size_bytes * 8 * 1_000_000_000 / self.rate_bps)'
)

# Bug 3: Hash uses (num_queues - 1) as divisor, leaving queue N-1 unused
# and causing flow_id collisions (e.g., flow 1 and flow 8 both map to
# queue 1 when num_queues=8, since 1%7 == 8%7 == 1).
code = code.replace(
    'qid = flow_id % (self.num_queues - 1)',
    'qid = flow_id % self.num_queues'
)

with open('/app/scheduler.py', 'w') as f:
    f.write(code)

print("Fixed 3 bugs in scheduler.py:")
print("  1. Added q.deficit += self.quantum in DRR schedule_round")
print("  2. Added * 8 in transmission time calculation (bytes -> bits)")
print("  3. Fixed flow hash modulo from (num_queues-1) to num_queues")
