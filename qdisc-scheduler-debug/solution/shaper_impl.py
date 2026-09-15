"""
Hierarchical traffic shaper: CAKE-inspired scheduler with strict priority
for latency-sensitive classes and weighted DRR for best-effort traffic.

Architecture:
  - DSCP-based flow classifier
  - Per-class DRR fair queuing among flows
  - Strict priority: voice > video
  - Weighted round-robin: best_effort (weight 6) vs background (weight 1)
  - Token-bucket rate caps on voice and video classes
  - Link-rate pacing via transmission-time accounting

"""

from collections import deque


class FlowQueue:
    __slots__ = ('flow_id', 'packets', 'deficit', 'needs_quantum')

    def __init__(self, flow_id):
        self.flow_id = flow_id
        self.packets = deque()
        self.deficit = 0
        self.needs_quantum = True

    def enqueue(self, pkt):
        self.packets.append(pkt)

    def peek(self):
        return self.packets[0] if self.packets else None

    def dequeue(self):
        return self.packets.popleft() if self.packets else None

    def is_empty(self):
        return len(self.packets) == 0


class DRRScheduler:
    """Deficit Round Robin scheduler for byte-fair queuing among flows."""

    def __init__(self, quantum=2000):
        self.quantum = quantum
        self.queues = {}
        self.active = deque()

    def enqueue(self, pkt):
        fid = pkt['flow_id']
        if fid not in self.queues:
            self.queues[fid] = FlowQueue(fid)
        fq = self.queues[fid]
        was_empty = fq.is_empty()
        fq.enqueue(pkt)
        if was_empty:
            fq.needs_quantum = True
            self.active.append(fq)

    def dequeue_one(self):
        """Return one packet using DRR, or None if no active flows."""
        if not self.active:
            return None

        limit = len(self.active) + 1
        for _ in range(limit):
            if not self.active:
                return None
            fq = self.active[0]

            if fq.needs_quantum:
                fq.deficit += self.quantum
                fq.needs_quantum = False

            if not fq.is_empty() and fq.peek()['size_bytes'] <= fq.deficit:
                pkt = fq.dequeue()
                fq.deficit -= pkt['size_bytes']
                if fq.is_empty():
                    self.active.popleft()
                    fq.deficit = 0
                    fq.needs_quantum = True
                elif fq.peek()['size_bytes'] > fq.deficit:
                    self.active.popleft()
                    self.active.append(fq)
                    fq.needs_quantum = True
                return pkt
            else:
                self.active.popleft()
                if not fq.is_empty():
                    self.active.append(fq)
                    fq.needs_quantum = True
                else:
                    fq.deficit = 0
                    fq.needs_quantum = True

        return None

    def has_packets(self):
        return len(self.active) > 0


class HierarchicalShaper:
    def __init__(self, spec):
        self.link_rate_bps = spec['link_rate_mbps'] * 1_000_000
        self.spec = spec

        self.dscp_map = {}
        self.classes = {}
        self.priority_classes = []
        self.weighted_classes = []

        for tc in spec['traffic_classes']:
            name = tc['name']
            self.dscp_map[tc['dscp']] = name

            if name == 'voice':
                quantum = 200
            elif name == 'video':
                quantum = 1500
            else:
                quantum = 2000

            rate_cap = None
            if 'rate_cap_mbps' in tc:
                rate_cap = tc['rate_cap_mbps'] * 1_000_000

            self.classes[name] = {
                'priority': tc['priority'],
                'weight': tc.get('weight', 1),
                'drr': DRRScheduler(quantum=quantum),
                'rate_cap_bps': rate_cap,
                'bucket_tokens': 0.0,
                'bucket_last_ns': 0,
            }

            if name in ('voice', 'video'):
                self.priority_classes.append((tc['priority'], name))
            else:
                self.weighted_classes.append((tc['priority'], name))

        self.priority_classes.sort()
        self.weighted_classes.sort()
        self.wrr_counter = 0
        self.all_packets = []

    def enqueue(self, pkt):
        self.all_packets.append(pkt)

    def _classify(self, pkt):
        return self.dscp_map.get(pkt['dscp'], 'best_effort')

    def _refill_bucket(self, name, now_ns):
        info = self.classes[name]
        if info['rate_cap_bps'] is None:
            return
        if info['bucket_last_ns'] == 0:
            info['bucket_last_ns'] = now_ns
            info['bucket_tokens'] = info['rate_cap_bps'] / 8 * 0.01
            return
        elapsed = now_ns - info['bucket_last_ns']
        burst = info['rate_cap_bps'] / 8 * 0.01
        added = elapsed * info['rate_cap_bps'] / 8 / 1e9
        info['bucket_tokens'] = min(burst, info['bucket_tokens'] + added)
        info['bucket_last_ns'] = now_ns

    def _class_can_send(self, name, now_ns):
        info = self.classes[name]
        if not info['drr'].has_packets():
            return False
        if info['rate_cap_bps'] is not None:
            self._refill_bucket(name, now_ns)
            return info['bucket_tokens'] >= 64
        return True

    def _select_priority(self, now_ns):
        for _, name in self.priority_classes:
            if self._class_can_send(name, now_ns):
                pkt = self.classes[name]['drr'].dequeue_one()
                if pkt:
                    info = self.classes[name]
                    if info['rate_cap_bps'] is not None:
                        info['bucket_tokens'] -= pkt['size_bytes']
                    return pkt
        return None

    def _select_weighted(self):
        available = []
        total_weight = 0
        for _, name in self.weighted_classes:
            info = self.classes[name]
            if info['drr'].has_packets():
                available.append((name, info))
                total_weight += info['weight']

        if not available:
            return None
        if len(available) == 1:
            return available[0][1]['drr'].dequeue_one()

        self.wrr_counter += 1
        pos = self.wrr_counter % total_weight
        cumulative = 0
        for name, info in available:
            cumulative += info['weight']
            if pos < cumulative:
                pkt = info['drr'].dequeue_one()
                if pkt:
                    return pkt
                break

        for name, info in available:
            pkt = info['drr'].dequeue_one()
            if pkt:
                return pkt
        return None

    def _select_packet(self, now_ns):
        pkt = self._select_priority(now_ns)
        if pkt:
            return pkt
        return self._select_weighted()

    def run(self):
        self.all_packets.sort(key=lambda p: p['arrival_ns'])

        output = []
        n_total = len(self.all_packets)
        if n_total == 0:
            return output

        arr_idx = 0
        link_free_ns = self.all_packets[0]['arrival_ns']

        while len(output) < n_total:
            while (arr_idx < n_total and
                   self.all_packets[arr_idx]['arrival_ns'] <= link_free_ns):
                pkt = self.all_packets[arr_idx]
                class_name = self._classify(pkt)
                self.classes[class_name]['drr'].enqueue(pkt)
                arr_idx += 1

            pkt = self._select_packet(link_free_ns)

            if pkt is not None:
                dequeue_ns = link_free_ns
                tx_ns = int(pkt['size_bytes'] * 8 * 1e9 / self.link_rate_bps)
                link_free_ns = dequeue_ns + tx_ns

                class_name = self._classify(pkt)
                output.append({
                    'dequeue_ns': dequeue_ns,
                    'flow_id': pkt['flow_id'],
                    'size_bytes': pkt['size_bytes'],
                    'dscp': pkt['dscp'],
                    'class_name': class_name,
                    'queue_id': pkt['flow_id'],
                    'scheduling_delay_ns': max(0,
                        dequeue_ns - pkt['arrival_ns']),
                })
            elif arr_idx < n_total:
                link_free_ns = self.all_packets[arr_idx]['arrival_ns']
            else:
                break

        return output
