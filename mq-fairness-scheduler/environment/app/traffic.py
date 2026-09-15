"""Traffic generation for multi-queue fair queuing simulation.

"""

import json


class TrafficGenerator:
    """Generates deterministic traffic patterns from scenario configuration."""

    def __init__(self, scenario_path):
        with open(scenario_path) as f:
            self.config = json.load(f)
        self.global_rate = self.config['global_rate_mbps'] * 1e6 / 8  # bytes/sec
        self.duration_sec = self.config['duration_sec']
        self.flows = self.config['flows']

    def get_active_flows(self, time_sec):
        """Returns list of active flow configs at given time."""
        return [f for f in self.flows
                if f['start_sec'] <= time_sec < f.get('end_sec', self.duration_sec + 1)]

    def get_flow_demand(self, flow, time_sec):
        """Returns demand in bytes/sec for a flow. Absent demand_mbps means unlimited."""
        demand = flow.get('demand_mbps')
        if demand is None:
            return float('inf')
        return demand * 1e6 / 8
