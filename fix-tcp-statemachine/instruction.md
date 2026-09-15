The TCP connection simulator at `/app/` establishes connections and transfers data over perfect (lossless) networks. Under realistic network conditions — packet loss, propagation delay, and packet reordering — transfers fail silently or deliver corrupted data.

Examine the simulator architecture in `/app/tcp_sim/`. A reference packet capture at `/app/reference/capture.pcap` demonstrates how a correct implementation handles a lossy link with retransmission and recovery — use `tshark -r /app/reference/capture.pcap -V` to study the sequence of events. The simulation harness at `/app/run_sim.py` exercises predefined scenarios (`python3 /app/run_sim.py --list-scenarios`) and reports transfer results as JSON; pipe through `jq` to inspect individual fields.

Extend the simulator to deliver data reliably and efficiently under all scenarios defined in `/app/scenarios/config.json`, including channels with up to 25% packet loss and 20% reordering. Existing lossless connection behavior must remain backwards-compatible.

`pytest /tests/test_state.py` defines the complete success criteria.