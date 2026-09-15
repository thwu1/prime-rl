# CSIG Protocol for Datacenter Congestion Control

CSIG (Congestion Signaling) is an in-band network telemetry protocol for datacenter
fabrics. Packets carry compact CSIG tags that are updated at each network hop via
compare-and-replace (max) semantics, accumulating worst-case congestion metrics along
the flow's path.

## Tag Fields

Each CSIG tag has two fields, both initialized to 0.0:

- **max_link_utilization**: the highest link utilization ratio seen on the path
- **max_virtual_queue_depth**: the highest virtual queue backlog seen on the path

At each link on the flow's path, the switch computes local metrics and updates:

    utilization = (sum of sending rates of all flows traversing this link) / link_capacity_mbps
    vqd = max(0, total_load_on_link - link_capacity_mbps) * 1000.0
    tag.max_link_utilization = max(tag.max_link_utilization, utilization)
    tag.max_virtual_queue_depth = max(tag.max_virtual_queue_depth, vqd)

The destination reflects the final tag values back to the sender.

## AIMD Rate Control

Each simulation round, every flow adjusts its sending rate based on the CSIG feedback:

- **Congested** (max_link_utilization > 1.0):
  rate = rate * (1 - beta * min(max_link_utilization - 1, 1))
- **Uncongested** (max_link_utilization <= 1.0):
  rate = rate + alpha * flow_weight
- Rates are clamped to a minimum of 0.01 Mbps

Parameters: alpha = 1.0 Mbps, beta = 0.5. Initial rate = flow_weight * alpha.

## Equilibrium and Fairness

CSIG-AIMD converges to the weighted max-min fair allocation. In topologies where flows
traverse multiple bottleneck links, the equilibrium corresponds to the progressive
filling solution: bottleneck links saturate in order of tightness, each step fixing the
rates of all flows constrained at that bottleneck and redistributing residual capacity
across remaining links that those flows also traverse.

Time-averaging sending rates over a post-warmup window smooths AIMD oscillations to
approximate the steady-state allocation.
