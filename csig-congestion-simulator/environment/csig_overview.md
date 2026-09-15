# CSIG (Congestion Signaling) Protocol Overview

CSIG is an in-band network telemetry protocol for datacenter congestion control.
Packets carry fixed-size CSIG tags that accumulate congestion metrics as they
traverse the network path from source to destination.

## Tag Format

Each CSIG tag contains two fields, both initialized to 0.0:

- **max_link_utilization** (float): highest link utilization ratio on the path
- **max_virtual_queue_depth** (float): highest virtual queue backlog on the path

## Hop-by-Hop Aggregation (Compare-and-Replace)

At each link on a flow's path, the switch computes local metrics and updates the
tag fields using the maximum operator:

- Link utilization = (sum of sending rates of all flows traversing this link) / link_capacity_mbps
- Virtual queue depth = max(0, total_load_on_link - link_capacity_mbps) * 1000.0
- tag.max_link_utilization = max(tag.max_link_utilization, local_utilization)
- tag.max_virtual_queue_depth = max(tag.max_virtual_queue_depth, local_vqd)

The final tag values at the destination reflect the worst-case metrics across the
entire path. The destination reflects these values back to the sender.

## AIMD Rate Control

Senders adjust their sending rate each round based on the aggregated CSIG tag:

- **Congested** (max_link_utilization > 1.0):
  `rate = rate * (1.0 - beta * min(max_link_utilization - 1.0, 1.0))`
- **Uncongested** (max_link_utilization <= 1.0):
  `rate = rate + alpha * flow_weight`
- Rates are clamped to a minimum of 0.01 Mbps

Recommended parameters: alpha = 1.0 Mbps, beta = 0.5.
Initial sending rate for each flow: flow_weight * alpha.

## Expected Behavior

The CSIG-AIMD mechanism converges to the **weighted max-min fair** allocation:
bandwidth on each bottleneck link is shared proportionally to flow weights. In
topologies with multiple interacting bottlenecks, a progressive filling process
determines the equilibrium — flows constrained by the tightest bottleneck settle
first, releasing residual capacity for remaining flows on less congested links.

Time-averaging the sending rates over a post-warmup window smooths the
oscillations inherent in AIMD dynamics to approximate the steady-state allocation.
