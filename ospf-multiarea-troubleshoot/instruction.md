A six-router FRRouting (FRR) topology has been provisioned with physical connectivity but no OSPF routing configuration. Skeleton configs (hostname only) are in `/app/configs/R{1-6}.conf`. The complete topology specification — including interface details, area type requirements, cost constraints, summarization rules, and redistribution policies — is in `/app/topology.json`.

## Topology

```
         Area 0 (Backbone)
  R1 ====== R2 ====== R3
  |          |          \
  | Area 1   | Area 1    \ Area 2
  |(T-Stub)  |(T-Stub)    \(NSSA)
  R4 ======= R5            R6 (ASBR)
```

Six links: R1-R2 (backbone), R2-R3 (backbone), R1-R4, R2-R5, R4-R5 (all Area 1), R3-R6 (Area 2). R6 has three pre-configured static routes (172.16.{0,1,2}.0/24).

## Task

Design and implement complete FRR OSPF configurations for all six routers in `/app/configs/` that simultaneously satisfy every requirement specified in `/app/topology.json`:

- All six OSPF adjacencies must reach FULL state with correct area assignments and compatible area type configurations across neighbors
- Area 1 must operate as totally stubby (ABRs suppress both inter-area and external LSAs, injecting only a default route; internal routers must use compatible area directives)
- Area 2 must operate as NSSA for external route injection
- ABRs must perform inter-area route summarization using `area range` directives as specified
- OSPF interface costs must be overridden where specified to enforce preferred path selection into Area 1
- R6's static route redistribution must use a route-map referencing a prefix-list that selectively permits two of three external prefixes and denies the third
- Permitted external routes must be visible on all backbone routers but must NOT appear on routers inside the totally stubby area

Run `/app/ospf_checker.py` to validate your design against all requirements.