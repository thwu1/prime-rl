You have 200 labeled self-driving car simulation tests at `/app/train_data.json` (with pass/fail outcomes and execution durations) and 50 unlabeled test cases at `/app/test_data.json` (road geometry only). The gRPC competition interface is defined in `/app/interface.proto` and the mathematical framework for road curvature analysis and evaluation metrics is documented in `/app/SPEC.md`.

Design and implement a test prioritization system that exploits road curvature characteristics to predict simulation failures. The system must implement the `CompetitionTool` gRPC service (launchable via `/app/start_server.sh` on port 50051), learn from oracle data streamed through `Initialize`, and return intelligent orderings through the bidirectional streaming `Prioritize` RPC.

The specification describes curvature profile theory — the transformation from coordinate sequences to kappa/arclength representations — which characterizes the geometric difficulty of road segments. Understanding how curvature distributes across a road, how it relates to vehicle dynamics failures, and how to balance fault detection rate against cost-weighted detection efficiency is essential for meeting the evaluation criteria.

Write an evaluation client that exercises the full gRPC pipeline (Name → Initialize → Prioritize) and produces `/app/results.json` conforming to the output schema in `/app/SPEC.md`.

Quality requirements:
- APFD ≥ 0.58
- APFDc ≥ 0.55
- All faults in the test set must appear within the first 90% of the prioritized ordering