Your organization's release pipeline enforces supply chain integrity through cryptographic artifact signing and attestation. The signing and attestation policy is at `/app/policy.json`.

Five release binaries were produced by the build system (canonical copies at `/app/build_output/`) and deployed to `/app/artifacts/`. The security team's integrity monitoring has detected that at least one deployed artifact no longer matches its build output — a post-deployment compromise is suspected.

An initial verification was performed (script at `/app/verify.sh`, results at `/app/audit_report.json`), but the security team has determined it is unreliable.

Investigate the deployed artifacts, implement the complete signing and attestation infrastructure defined by the policy using the canonical build outputs as the source of truth for all cryptographic operations, and produce a correct verification pipeline that evaluates the deployed artifacts and generates a trustworthy audit report.

Expected output locations:
- Key pairs: `/app/keys/{team}.key` (private) and `/app/keys/{team}.pub` (public, PEM-encoded)
- Signature bundles: `/app/bundles/{artifact}.{team}.bundle` (JSON)
- Attestation files: `/app/attestations/{artifact}.{type}.statement` and `/app/attestations/{artifact}.{type}.bundle`
- Verification script: `/app/verify.sh` (executable, must produce `/app/audit_report.json` when run)

Audit report schema:

```json
{
  "artifacts": [
    {
      "name": "<filename>",
      "overall": "pass" | "fail",
      "signatures": [{"signer": "<team>", "status": "pass" | "fail"}],
      "attestations": [{"type": "<type>", "status": "pass" | "fail"}]
    }
  ],
  "summary": {"total": 5, "passed": <n>, "failed": <n>}
}
```

Every artifact must appear in the report. Compromised artifacts must report `"overall": "fail"`. `summary.passed + summary.failed` must equal `summary.total` (5), with at least 1 failure.