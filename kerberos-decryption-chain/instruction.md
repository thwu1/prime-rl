The enterprise domain `ACME.CORP` has experienced a suspected golden ticket attack. Incident artifacts have been collected in `/app/incident/`.

## Artifacts

- `/app/incident/keytabs/` — Three MIT-format keytab files extracted from domain servers, each containing one or more service principal keys across multiple encryption types and key versions
- `/app/incident/tickets/` — Six DER-encoded Kerberos tickets captured from network traffic during the incident window
- `/app/incident/manifest.json` — Environment context (realm, known legitimate users) and the exact JSON schema your report must follow

## Objective

Analyze the incident artifacts and produce a forensic report at `/app/report.json`. The manifest defines the required report schema, which covers: a complete inventory of all keytab entries, the decrypted contents of every captured ticket (matched to the key that decrypted it), identification of anomalous tickets that indicate compromise, and attribution of the attack to a specific keytab and principal.

Scapy with its cryptography backend is available in the environment.