Evidence from a penetration test against INLANEFREIGHT Corp has been staged in `/app/enterprise/`. Artifacts span three compromised hosts across different network segments: a DMZ web server (`dmz-web01`), an internal application server (`internal-app01`), and a domain controller (`dc01`).

The environment reflects a post-incident state: the blue team has disabled accounts and revoked ACL delegations in response to the breach, but at least one indirect privilege escalation path to Domain Admin survives. Credential artifacts are chained — each recovered credential unlocks the next stage. The classified intelligence document on dc01 is encrypted with a non-standard custom encryption tool (found on `internal-app01`) rather than standard OpenSSL.

Your objectives:

1. Recover credentials through the chain of evidence across all three hosts, including decrypting a GPP `cpassword` and an OpenSSL-encrypted credential vault.
2. Evaluate the AD security graph at `/app/enterprise/dc01/ad_graph.json` to identify which domain account retains an active, complete privilege escalation path to `domain_admins` — considering disabled/locked accounts and revoked ACL edges.
3. Crack the NTLM hash of the account with effective Domain Admin access.
4. Reverse-engineer the custom vault encryption tool on `internal-app01` and use it to decrypt the classified document on `dc01`.

Write your results to:
- `/app/results/da_password.txt` — the cleartext password of the account with effective Domain Admin access
- `/app/results/viable_path.json` — JSON array of ordered node IDs forming the viable escalation path from the target account to `domain_admins` (e.g., `["account", "group1", ..., "domain_admins"]`)
- `/app/results/decrypted_document.txt` — the full decrypted contents of `classified.enc`