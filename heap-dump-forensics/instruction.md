A HeapService instance was compromised. The following artifacts are available at `/app/`:

- `heapservice` — the stripped service binary (ELF, x86-64)
- `snapshot_clean.bin` — heap memory snapshot captured before the incident
- `snapshot_attacked.bin` — heap memory snapshot captured after the incident was detected
- `heapservice_notes.c` — system and forensic documentation from the infrastructure team

Between the two snapshots, the heap underwent multiple modifications — some from normal service operations, others from attacker-induced corruption. The attack was detected and halted before the attacker achieved their objective.

Produce the following three deliverables:

1. `/app/heap_validator.py` — A detection tool that determines whether any heap snapshot from this service has been tampered with. It must accept a single command-line argument (path to a snapshot file) and print a JSON object to stdout with this schema: `{"compromised": <bool>, "poisoned_bins": [<int>, ...], "target_address": "<hex_string>" or null}`. The tool must correctly classify arbitrary snapshots from this service, not just the two provided.

2. `/app/forensic_report.txt` — For every heap chunk that differs between the two snapshots, classify the modification as **BENIGN** or **MALICIOUS** with a technical justification. Include an **ATTACK IMPACT ASSESSMENT** section covering: (a) the attacker's specific objective, (b) exploit viability if not interrupted, (c) sensitive data at risk, and (d) a severity rating (CRITICAL/HIGH/MEDIUM/LOW) with justification.

3. `/app/flag.txt` — The decrypted plaintext of the encrypted session token found in one of the heap slots.