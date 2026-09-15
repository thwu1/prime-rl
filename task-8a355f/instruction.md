Three engineers have each submitted a competing proposal for securing a multi-tenant Kubernetes cluster with four production namespaces (`prod-frontend`, `prod-backend`, `prod-data`, `monitoring`). Each proposal is a complete set of YAML manifests — NetworkPolicies, RBAC resources, ResourceQuotas, LimitRanges, and Deployment definitions with security contexts — located at `/app/proposal-a/`, `/app/proposal-b/`, and `/app/proposal-c/`.

The cluster's required security posture is defined in `/app/security-requirements.yaml`.

No single proposal is fully compliant. Each makes different trade-offs and contains different defects across the security domains. You must independently determine what each proposal gets right and wrong by carefully analyzing the manifests against the requirements specification.

Evaluate all three proposals against the security requirements across these eight categories: `default_deny`, `cross_namespace_selectors`, `egress_policies`, `rbac_scoping`, `rbac_least_privilege`, `resource_quotas`, `limit_ranges`, `security_contexts`. Write a compliance evaluation to `/app/evaluation-report.json` structured as:

```json
{
  "proposal_a": {"default_deny": "pass"|"fail", ...all 8 categories...},
  "proposal_b": {"default_deny": "pass"|"fail", ...all 8 categories...},
  "proposal_c": {"default_deny": "pass"|"fail", ...all 8 categories...}
}
```

Then design and produce a fully compliant configuration by selecting the correct elements from each proposal and correcting any remaining defects. Write the synthesized manifests to `/app/final-config/` using these files: `deployments.yaml`, `network-policies.yaml`, `rbac.yaml`, `resource-management.yaml`. The final configuration must pass every requirement in the security policy.