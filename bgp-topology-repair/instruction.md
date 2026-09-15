You are the newly assigned network architect for AS 65100, a dual-homed enterprise connected to two upstream ISPs. The previous engineer configured interface addressing on all five routers but departed before implementing any routing protocols or policies. The network is non-functional.

Diagnostic reports in `/app/diagnostics/` document seven critical issues observed during testing, the organizational routing policies, and architectural notes from the previous engineer. Skeleton configurations with only interface addressing are at `/app/configs/r1.conf` through `/app/configs/r5.conf`. FRR is installed.

Analyze all diagnostic documents, determine the root causes of each reported issue, and implement complete working FRR routing configurations for all five routers that resolve every issue and satisfy all policies in `/app/diagnostics/network_policy.txt`.

## Topology

```
     R4 (AS 65200, ISP-Alpha)         R5 (AS 65300, ISP-Beta)
          |                                 |
          |                                 |
          |                                 |
         R1 ─────────── R3 ─────────── R2
              10.0.13.0/24    10.0.23.0/24
                       AS 65100
```

| Router | Loopback | Interfaces |
|--------|----------|------------|
| R1 | 10.255.0.1/32 | eth0: 10.0.13.1/24 (→R3), eth1: 10.0.14.1/24 (→R4) |
| R2 | 10.255.0.2/32 | eth0: 10.0.23.2/24 (→R3), eth1: 10.0.25.2/24 (→R5) |
| R3 | 10.255.0.3/32 | eth0: 10.0.13.3/24 (→R1), eth1: 10.0.23.3/24 (→R2) |
| R4 | 10.255.1.4/32 | eth0: 10.0.14.4/24 (→R1) |
| R5 | 10.255.2.5/32 | eth0: 10.0.25.5/24 (→R2) |