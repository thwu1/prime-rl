A 3-second multi-class network traffic capture is at `/app/capture.pcap` containing 20 multiplexed UDP flows across four QoS classes (voice, video, best_effort, background), each tagged with distinct DSCP values. The SLA specification is at `/app/sla_spec.json`. A broken tc/HTB qdisc configuration is at `/app/tc_template.sh`.

Produce all three deliverables:

**`/app/tshark_extract.sh`** — Shell script that uses `tshark` to extract per-packet fields from the pcap and writes `/app/trace.csv` with columns `arrival_ns`, `flow_id`, `size_bytes`, `dscp`. Flows are identified by UDP source port (the spec documents the port-to-flow mapping). `size_bytes` corresponds to `ip.len`. Arrival timestamps are nanoseconds derived from capture timestamps.

**`/app/tc_config.sh`** — Corrected version of `/app/tc_template.sh`. The template contains three distinct bugs that would prevent correct QoS enforcement on a real interface. Identify and fix all three.

**`/app/shaper.py`** — Python module exporting a `HierarchicalShaper` class compatible with `/app/run_shaper.py`. The shaper reads the trace produced by your extraction script, classifies packets by DSCP, and schedules them through a rate-limited 50 Mbps link satisfying every per-class SLA defined in the spec. Running `python3 /app/run_shaper.py` must produce `/app/output.csv`.

All per-class SLAs must be met simultaneously. Shaper output must conserve all packets and bytes, maintain monotonically non-decreasing dequeue timestamps, and provide per-flow queue isolation.