def assertion_to_clinical_status:
  if . == "historical" then "resolved"
  else "active"
  end;

def assertion_to_verification_status:
  if . == "affirmed" or . == "historical" then "confirmed"
  elif . == "negated" then "refuted"
  elif . == "hypothetical" then "provisional"
  else "unconfirmed"
  end;

{
  resourceType: "Bundle",
  type: "collection",
  entry: [
    .[] | .note_id as $nid |
    .entities[] |
    select(.type == "CONDITION" or .type == "SYMPTOM") |
    {
      resource: {
        resourceType: "Condition",
        id: ($nid + "-" + (.start | tostring)),
        clinicalStatus: {
          coding: [{
            system: "http://terminology.hl7.org/CodeSystem/condition-clinical",
            code: (.assertion | assertion_to_clinical_status)
          }]
        },
        verificationStatus: {
          coding: [{
            system: "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            code: (.assertion | assertion_to_verification_status)
          }]
        },
        code: {
          coding: [{
            system: "http://hl7.org/fhir/sid/icd-10-cm",
            code: .resolved_code,
            display: .resolved_term
          }],
          text: .text
        },
        subject: { reference: "Patient/unknown" },
        note: [{ text: ("Source note: " + $nid) }]
      }
    }
  ]
}
