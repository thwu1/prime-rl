CISA ScubaGear's Rego policies for Microsoft Entra ID (AAD) baseline security are installed at `/app/rego/`. These policies evaluate a tenant's security posture against CISA's Secure Configuration Baselines using Open Policy Agent (OPA), available at `/usr/local/bin/opa`.

A target compliance specification at `/app/target_outcomes.json` maps 20 policy IDs to required `RequirementMet` values (`true` = pass, `false` = fail). Three of the twenty policies must specifically **fail** while the remaining seventeen must **pass**.

Create `/app/tenant_input.json` -- a JSON file representing a simulated M365 tenant configuration -- that produces the exact `RequirementMet` outcomes specified in `target_outcomes.json` when evaluated with:

```
opa eval "data.aad.tests" -i /app/tenant_input.json -d /app/rego/ --format json
```

The output contains test result objects each with a `PolicyId` and `RequirementMet` field. Policy interdependencies exist -- one policy's result can affect another's evaluation path. Some policies require specific input structures to be intentionally absent or insufficient to produce a `false` outcome.