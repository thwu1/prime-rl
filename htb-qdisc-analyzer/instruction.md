A production server with two shaped interfaces (eth0, eth1) has HTB qdisc hierarchies configured via `tc` and nftables-based packet classification. Raw command output captures from this server are at `/app/captures/`:

- `eth0_qdisc.txt`, `eth1_qdisc.txt` — `tc -s -d qdisc show dev <iface>`
- `eth0_class.txt`, `eth1_class.txt` — `tc -s -d class show dev <iface>`
- `eth0_filter.txt`, `eth1_filter.txt` — `tc -s -d filter show dev <iface>` (fw mark filters)
- `nft_ruleset.txt` — `nft list ruleset` (fwmark-setting rules for tc classification)
- `ip_link.txt` — `ip -d link show`

SLA requirements are in `/app/sla_requirements.json`.

The configurations contain multiple deliberate misconfigurations spanning the tc class hierarchy and the nftables-to-tc integration.

Create `/app/tc_forensic.py` that parses these raw text captures and writes `/app/forensic_report.json` with these top-level keys:

**`validation_errors`** — All misconfigurations and inconsistencies. Each entry: `type` (string), `interface` (string), an identifier for the affected element (`class`, `qdisc`, `filter_handle`, or `mark` as applicable), and `details` (string). Errors span both intra-tool issues (orphan classes, ceil violations, rate oversubscription, missing default targets, invalid filter targets) and cross-tool mismatches (nft marks without corresponding tc filters).

**`leaf_allocations`** — Per-interface mapping of leaf class IDs (e.g. `"1:11"`) to their steady-state bandwidth in Mbps when all leaves are fully backlogged, computed as the Linux kernel's HTB scheduler would distribute it. Each interface's leaf allocations must sum to the root class rate. The allocation must account for HTB's priority-based scheduling and quantum-weighted distribution of excess bandwidth through the hierarchy.

**`sla_violations`** — Array of `{class, interface, required_mbps, actual_mbps}` for each SLA requirement the computed allocation fails to meet.

**`nft_mark_map`** — Per-interface mapping of hex fwmark strings (e.g. `"0xa"`) to the tc class they resolve to. Only include marks that have a corresponding tc fw filter on that interface.

Constraints:
- Parse native text output — no structured/JSON input is provided
- Handle mixed rate units (Gbit, Mbit) and noisy multi-line tc output with statistics, burst calculations, and token counts
- Executable as `python3 /app/tc_forensic.py`