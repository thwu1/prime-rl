The `/app/` directory contains an organization's NIST OSCAL compliance document set:

- `/app/catalog.json` — NIST SP 800-53 Rev 5 security controls catalog (families: AC, AU, CM, IA, SC)
- `/app/baseline_profile.json` — Moderate security baseline profile
- `/app/org_profile.json` — Organizational customization profile with exclusions, parameter assignments, and alterations
- `/app/system_ssp.json` — System Security Plan with control implementations
- `/app/poam.xml` — Plan of Action and Milestones (OSCAL XML format, namespace `http://csrc.nist.gov/ns/oscal/1.0`)

These documents form a layered hierarchy: profiles import other profiles or catalogs, applying selections, exclusions, and modifications. The organizational profile is the authoritative source for what the system must comply with.

Produce two outputs:

1. `/app/resolved_catalog.json` — The fully resolved catalog representing the effective set of controls required by the organizational profile after all imports, selections, exclusions, and modifications have been applied through the entire profile chain.

2. `/app/audit_report.json` — A compliance posture assessment with this structure:

```json
{
  "resolved_profile": {
    "required_controls": ["<sorted control IDs from the resolved catalog>"],
    "total_required": "<int>",
    "excluded_controls": ["<control IDs explicitly excluded by the org profile>"]
  },
  "gap_analysis": {
    "missing_controls": ["<sorted: required controls absent from SSP>"],
    "incomplete_implementations": {
      "<control-id>": {
        "missing_statements": ["<top-level statement item IDs from catalog not covered in SSP>"]
      }
    },
    "parameter_gaps": {
      "<control-id>": {
        "missing": ["<profile-assigned param IDs not set in SSP implemented-requirements>"]
      }
    },
    "extraneous_controls": ["<sorted: SSP controls not required by resolved profile>"],
    "orphaned_component_refs": ["<component UUIDs referenced in SSP by-components but not declared in system-implementation>"]
  },
  "compliance_summary": {
    "controls_implemented": "<int: required controls present in SSP>",
    "controls_required": "<int>",
    "controls_fully_compliant": "<int>",
    "compliance_percentage": "<float, 2 decimal places>"
  },
  "remediation_tracking": {
    "poam_items": [
      {
        "poam_uuid": "<POAM item UUID>",
        "control_id": "<affected control ID from linked observation>",
        "title": "<POAM item title>",
        "status": "<POAM item remediation status>",
        "risk_status": "<status of the associated risk entry>",
        "gap_type": "<missing_control|incomplete_statements|parameter_gap>"
      }
    ],
    "gaps_with_poam": ["<sorted: control IDs with both a gap and a POAM entry>"],
    "gaps_without_poam": ["<sorted: control IDs with a gap but no POAM entry>"],
    "total_poam_items": "<int>",
    "remediation_in_progress": "<int>",
    "remediation_completed": "<int>",
    "risk_accepted": "<int>"
  }
}
```

A control is "fully compliant" when it is present in the SSP with complete top-level statement item coverage and all profile-required parameters set.