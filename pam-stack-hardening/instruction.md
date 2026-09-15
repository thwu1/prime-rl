A Linux server was compromised through a chain of PAM configuration weaknesses. You are the incident responder.

Evidence and requirements are at `/app/`:
- `/app/auth_log.txt` — authentication log excerpt covering the breach window
- `/app/incident_report.txt` — SOC incident report with timeline, observations, and the required vulnerability assessment JSON schema
- `/app/operational_requirements.txt` — the system's security and operational requirements

The current PAM configuration under `/etc/pam.d/` (`common-auth`, `common-account`, `common-session`, `common-password`, `su`) and security parameter files under `/etc/security/` (`faillock.conf`, `limits.conf`, `access.conf`, `pwquality.conf`) contain multiple vulnerabilities. Some were actively exploited in this breach; others are latent risks.

When complete, the system must satisfy all of the following:

- Every vulnerability in the PAM stack — both exploited and latent — is remediated, and the configuration meets all requirements in `/app/operational_requirements.txt`
- All existing users can still authenticate with their current passwords
- A file `/app/vulnerability_assessment.json` exists, conforming to the schema in the incident report, that correctly identifies every vulnerability with its severity and whether it was exploited, and includes a causal attack chain reflecting the actual progression observed in the logs (the chain must correctly distinguish exploited from latent vulnerabilities, assign appropriate severity ratings, and order entries to match the causal progression)

You can compile C programs against libpam (`security/pam_appl.h`, link with `-lpam`) to test PAM behavior.