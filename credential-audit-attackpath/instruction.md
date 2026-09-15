During an authorized penetration test of ACME Corp (domain `ACMECORP.LOCAL`), an NTDS.dit database was extracted via DCSync. Your task is to perform offline password analysis against the hash dump, audit compliance with the domain password policy, and map viable attack paths from cracked accounts through the Active Directory structure to Domain Admin.

## Environment

- `/app/loot/ntds_dump.txt` — NTLM hash dump in secretsdump format (`DOMAIN\user:RID:LM:NT:::`)
- `/app/config/ad_structure.json` — AD graph data: users, groups, memberships, ACLs, delegation settings, and computer objects
- `/app/config/password_policy.json` — Domain password policy (length, complexity, age, lockout)
- `/app/wordlists/base.txt` — Base wordlist compiled from OSINT reconnaissance
- `/app/wordlists/company_terms.txt` — Company-specific terms gathered during engagement

## Deliverable

Write a JSON report to `/app/report/findings.json` with the following structure:

- `cracked_credentials`: object mapping each cracked `samaccountname` to its plaintext password
- `total_cracked`: integer count of cracked accounts
- `policy_violations`: object with keys `too_short` (array of usernames with passwords under minimum length), `no_uppercase` (array missing uppercase), `no_lowercase` (array missing lowercase), `no_digit` (array missing digits), `no_special` (array missing special characters)
- `total_policy_violations`: integer count of unique accounts with at least one violation
- `attack_paths`: array of objects, each describing a path from a cracked account to Domain Admins with fields: `start_account`, `path_steps` (array of objects with `from`, `to`, `technique`, `description`), `total_steps` (integer)
- `most_dangerous_account`: the `samaccountname` of the cracked account that has both the shortest attack path to Domain Admins AND at least one password policy violation (if multiple accounts tie on path length and both have violations, choose the one whose password is shortest)
- `risk_summary`: object with `accounts_with_da_path` (integer count of cracked accounts having any path to DA), `shortest_path_steps` (integer), `critical_misconfigurations` (array of strings describing the key ACL/delegation misconfigurations enabling the paths)

The attack path analysis must account for all abusable AD permissions including GenericAll, GenericWrite, WriteDACL, constrained delegation (S4U2Self/S4U2Proxy), SeBackupPrivilege, ReadGMSAPassword, and group membership chains. Non-abusable permissions (ReadProperty alone, standard group memberships without escalation potential) should not appear as attack path steps.