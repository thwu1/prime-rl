
# Incident Report: L4 Load Balancer Failure

## Summary

Production L4 load balancer experienced three categories of failure before the
node itself went down. A packet capture was recovered from the failed node.

## Environment

- **VIP**: 10.0.0.100 (UDP port 80)
- **Backends**: 10.0.0.1, 10.0.0.2, 10.0.0.3, 10.0.0.4
- **Expected behavior**: approximately equal traffic distribution across all four backends

## Timeline (UTC)

| Time  | Event |
|-------|-------|
| 14:00 | Normal operation begins |
| 14:05 | Traffic distribution anomaly noticed -- one backend handling disproportionate load |
| 14:23 | Overloaded backend removed for maintenance |
| 14:23 | Massive connection disruption observed (~75% of flows affected) |
| 14:25 | Second backend crashes, health checks continue reporting it as healthy |
| 14:40 | Load balancer node fails; packet capture recovered |

## Observed Symptoms

1. **Uneven distribution**: One backend consistently received roughly 45% of all
   response traffic, while the others received 12-30%. The expected share per
   backend was ~25%.

2. **Excessive disruption on backend removal**: When the overloaded backend was
   taken out of service, approximately 75% of active connections were disrupted
   (retransmits and resets observed). Only ~25% disruption was expected (flows
   that had been assigned to the removed backend).

3. **Stale health state**: After the second backend crashed, the load balancer
   continued treating it as healthy for approximately 45 seconds.

## Evidence

- Packet capture: `/app/captures/incident.pcap`
