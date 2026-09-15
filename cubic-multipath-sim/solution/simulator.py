#!/usr/bin/env python3
"""
QUIC Multipath CUBIC Congestion Control Simulator
Implements RFC 9438 CUBIC with multipath, spurious recovery, and ECN alternative backoff.
"""

import json
import math
import sys
import argparse


class CubicPathController:
    """Per-path CUBIC congestion controller (RFC 9438)."""

    def __init__(self, path_id, rtt_ms, mss, initial_cwnd_mss, C, beta, ecn_beta):
        self.path_id = path_id
        self.rtt_ms = rtt_ms
        self.rtt_s = rtt_ms / 1000.0
        self.mss = mss
        self.C = C
        self.beta = beta
        self.ecn_beta = ecn_beta

        self.cwnd = initial_cwnd_mss * mss
        self.ssthresh = float('inf')
        self.W_max = 0.0          # MSS units
        self.t_epoch_ms = None    # time of last congestion event
        self.K = 0.0              # seconds
        self.in_slow_start = True
        self.last_W_max = 0.0     # for fast convergence

        self._saved = None

        self.loss_events = 0
        self.ecn_events = 0
        self.spurious_recoveries = 0
        self.bytes_delivered = 0.0
        self.cwnd_at_events = []
        self.last_update_ms = 0

    def _save_state(self):
        self._saved = {
            'cwnd': self.cwnd,
            'ssthresh': self.ssthresh,
            'W_max': self.W_max,
            't_epoch_ms': self.t_epoch_ms,
            'K': self.K,
            'in_slow_start': self.in_slow_start,
            'last_W_max': self.last_W_max,
        }

    def _restore_state(self):
        if self._saved is None:
            return
        s = self._saved
        self.cwnd = s['cwnd']
        self.ssthresh = s['ssthresh']
        self.W_max = s['W_max']
        self.t_epoch_ms = s['t_epoch_ms']
        self.K = s['K']
        self.in_slow_start = s['in_slow_start']
        self.last_W_max = s['last_W_max']
        self._saved = None

    def _cubic_cwnd_at(self, t_ms):
        """Compute CUBIC congestion avoidance cwnd at time t_ms (bytes)."""
        if self.t_epoch_ms is None:
            return self.cwnd
        t_elapsed_s = (t_ms - self.t_epoch_ms) / 1000.0
        if t_elapsed_s < 0:
            return self.cwnd

        W_cubic = self.C * ((t_elapsed_s - self.K) ** 3) + self.W_max
        W_est = (self.W_max * self.beta +
                 3.0 * (1.0 - self.beta) / (1.0 + self.beta) *
                 t_elapsed_s / self.rtt_s)
        cwnd_mss = max(W_cubic, W_est)
        return max(cwnd_mss * self.mss, float(self.mss))

    def advance_to(self, t_ms):
        """Advance controller to time t_ms, updating cwnd and bytes_delivered."""
        if t_ms <= self.last_update_ms:
            return

        elapsed_ms = t_ms - self.last_update_ms
        old_cwnd = self.cwnd

        if self.in_slow_start:
            n_rtts = elapsed_ms / self.rtt_ms
            new_cwnd = self.cwnd * (2.0 ** n_rtts)

            if new_cwnd >= self.ssthresh and old_cwnd < self.ssthresh:
                cross_rtts = math.log2(self.ssthresh / old_cwnd)
                cross_ms = cross_rtts * self.rtt_ms
                avg_ss = (old_cwnd + self.ssthresh) / 2.0
                self.bytes_delivered += avg_ss * cross_ms / self.rtt_ms

                self.cwnd = self.ssthresh
                self.in_slow_start = False

                remaining_ms = elapsed_ms - cross_ms
                if remaining_ms > 0 and self.t_epoch_ms is not None:
                    old_cubic = self.cwnd
                    self.cwnd = self._cubic_cwnd_at(t_ms)
                    avg_ca = (old_cubic + self.cwnd) / 2.0
                    self.bytes_delivered += avg_ca * remaining_ms / self.rtt_ms
                elif remaining_ms > 0:
                    self.bytes_delivered += self.cwnd * remaining_ms / self.rtt_ms
            elif new_cwnd >= self.ssthresh:
                self.cwnd = self.ssthresh
                self.in_slow_start = False
                avg = (old_cwnd + self.cwnd) / 2.0
                self.bytes_delivered += avg * elapsed_ms / self.rtt_ms
            else:
                self.cwnd = new_cwnd
                avg = (old_cwnd + self.cwnd) / 2.0
                self.bytes_delivered += avg * elapsed_ms / self.rtt_ms
        else:
            self.cwnd = self._cubic_cwnd_at(t_ms)
            avg = (old_cwnd + self.cwnd) / 2.0
            self.bytes_delivered += avg * elapsed_ms / self.rtt_ms

        self.last_update_ms = t_ms

    def handle_loss(self, t_ms):
        """Process a loss-triggered congestion event."""
        self.advance_to(t_ms)
        self._save_state()

        cwnd_mss = self.cwnd / self.mss

        # Fast convergence (RFC 9438 Section 4.8)
        if cwnd_mss < self.last_W_max:
            self.last_W_max = cwnd_mss
            self.W_max = cwnd_mss * (1.0 + self.beta) / 2.0
        else:
            self.last_W_max = cwnd_mss
            self.W_max = cwnd_mss

        self.cwnd = max(self.cwnd * self.beta, float(self.mss))
        self.ssthresh = self.cwnd
        self.in_slow_start = False
        self.t_epoch_ms = t_ms
        self.K = ((self.W_max * (1.0 - self.beta)) / self.C) ** (1.0 / 3.0)

        self.loss_events += 1
        self.cwnd_at_events.append({
            'time_ms': t_ms,
            'cwnd_after_bytes': round(self.cwnd, 2),
            'event_type': 'loss'
        })

    def handle_ecn(self, t_ms):
        """Process an ECN-triggered congestion event (lighter backoff)."""
        self.advance_to(t_ms)
        self._save_state()

        cwnd_mss = self.cwnd / self.mss
        self.last_W_max = cwnd_mss
        self.W_max = cwnd_mss

        self.cwnd = max(self.cwnd * self.ecn_beta, float(self.mss))
        self.ssthresh = self.cwnd
        self.in_slow_start = False
        self.t_epoch_ms = t_ms
        self.K = ((self.W_max * (1.0 - self.ecn_beta)) / self.C) ** (1.0 / 3.0)

        self.ecn_events += 1
        self.cwnd_at_events.append({
            'time_ms': t_ms,
            'cwnd_after_bytes': round(self.cwnd, 2),
            'event_type': 'ecn'
        })

    def handle_spurious_recovery(self, t_ms):
        """Recover from a spurious congestion event by restoring pre-event state."""
        self.advance_to(t_ms)

        if self._saved is not None:
            self._restore_state()

        self.spurious_recoveries += 1
        self.cwnd_at_events.append({
            'time_ms': t_ms,
            'cwnd_after_bytes': round(self.cwnd, 2),
            'event_type': 'spurious_recovery'
        })

    def get_scheduling_weight(self):
        """Scheduling weight for multipath: lower is preferred."""
        cwnd_mss = self.cwnd / self.mss
        if cwnd_mss <= 0:
            return float('inf')
        return self.rtt_ms / cwnd_mss


def run_simulation(scenario):
    """Run a CUBIC congestion control simulation from a scenario dict.

    Args:
        scenario: dict with 'params', 'paths', 'events', 'duration_ms'

    Returns:
        dict with per-path results, total_bytes_delivered, multipath_schedule
    """
    params = scenario['params']
    mss = params['mss_bytes']
    C = params['cubic_C']
    beta = params['cubic_beta']
    ecn_beta = params['ecn_beta']
    initial_cwnd_mss = params['initial_cwnd_mss']
    duration_ms = scenario['duration_ms']

    controllers = {}
    for path_cfg in scenario['paths']:
        pid = path_cfg['id']
        controllers[pid] = CubicPathController(
            path_id=pid,
            rtt_ms=path_cfg['rtt_ms'],
            mss=mss,
            initial_cwnd_mss=initial_cwnd_mss,
            C=C,
            beta=beta,
            ecn_beta=ecn_beta
        )

    events = sorted(scenario.get('events', []), key=lambda e: e['time_ms'])
    min_rtt = min(c.rtt_ms for c in controllers.values())

    schedule_decisions = {pid: 0 for pid in controllers}
    event_idx = 0
    t = 0

    while t <= duration_ms:
        # Process events at or before current time
        while event_idx < len(events) and events[event_idx]['time_ms'] <= t:
            ev = events[event_idx]
            pid = ev['path_id']
            ctrl = controllers[pid]
            if ev['type'] == 'loss':
                ctrl.handle_loss(ev['time_ms'])
            elif ev['type'] == 'ecn':
                ctrl.handle_ecn(ev['time_ms'])
            elif ev['type'] == 'spurious_recovery':
                ctrl.handle_spurious_recovery(ev['time_ms'])
            event_idx += 1

        # Advance all controllers to current time
        for ctrl in controllers.values():
            ctrl.advance_to(t)

        # Multipath scheduling decision
        if len(controllers) > 1:
            best = min(controllers.keys(),
                       key=lambda p: controllers[p].get_scheduling_weight())
            schedule_decisions[best] += 1

        t += min_rtt

    # Final advance
    for ctrl in controllers.values():
        ctrl.advance_to(duration_ms)

    # Build result
    result = {
        'paths': {},
        'total_bytes_delivered': 0.0,
        'multipath_schedule': {str(k): v for k, v in schedule_decisions.items()}
    }

    for pid in sorted(controllers.keys()):
        ctrl = controllers[pid]
        result['paths'][str(pid)] = {
            'final_cwnd_bytes': round(ctrl.cwnd, 2),
            'loss_events': ctrl.loss_events,
            'ecn_events': ctrl.ecn_events,
            'spurious_recoveries': ctrl.spurious_recoveries,
            'bytes_delivered': round(ctrl.bytes_delivered, 2),
            'cwnd_at_events': ctrl.cwnd_at_events
        }
        result['total_bytes_delivered'] += ctrl.bytes_delivered

    result['total_bytes_delivered'] = round(result['total_bytes_delivered'], 2)
    return result


def main():
    parser = argparse.ArgumentParser(
        description='QUIC Multipath CUBIC Congestion Control Simulator')
    parser.add_argument('--scenario', required=True, help='Scenario JSON file')
    parser.add_argument('--output', required=True, help='Output JSON file')
    args = parser.parse_args()

    with open(args.scenario) as f:
        scenario = json.load(f)

    result = run_simulation(scenario)

    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    return 0


if __name__ == '__main__':
    sys.exit(main())
