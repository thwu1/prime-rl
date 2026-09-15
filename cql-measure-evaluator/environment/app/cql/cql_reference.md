# CQL Reference Guide for CMS165 Evaluation

## Key CQL Concepts

### Value Set Matching
`[Condition: "Essential Hypertension"]` retrieves all Condition resources whose `code` contains
a coding that matches the "Essential Hypertension" value set. Similarly, `[Encounter: "Office Visit"]`
matches Encounter resources whose `type` field (a list of CodeableConcept) contains a matching code.

Match semantics: a resource matches a value set if **any** coding in its relevant field
(Condition.code, Encounter.type, Procedure.code, Observation.code) has a (system, code) pair
found in the terminology database at `/app/terminology.db`. Query value set membership by joining
the `value_sets` table (matched on `title`) with the `codes` table (matched on `system` and `code`).

### Blood Pressure Observations
Blood pressure observations use LOINC code `85354-9` ("Blood pressure panel") as their primary
`code`. Each BP observation has `component` entries:
- Systolic: component.code = LOINC `8480-6`, component.valueQuantity.value = mmHg reading
- Diastolic: component.code = LOINC `8462-4`, component.valueQuantity.value = mmHg reading

A single observation may have both components, or only one. The "Most Recent Blood Pressure Day"
algorithm requires that a date appear in **both** the set of dates with qualifying systolic readings
**and** the set of dates with qualifying diastolic readings (set intersection).

### Encounter Class Codes
FHIR Encounters have a `class` field using the v3-ActCode system:
- `AMB` = ambulatory (office visits, outpatient)
- `EMER` = emergency department
- `IMP` = inpatient
- `ACUTE` = inpatient acute
- `NONAC` = inpatient non-acute
- `PRENC` = pre-admission
- `SS` = short stay
- `HH` = home health

### Condition Clinical Status
A condition is "active" if its `clinicalStatus` coding has code `active`, `recurrence`, or `relapse`
(system: `http://terminology.hl7.org/CodeSystem/condition-clinical`).

### Prevalence Interval
For a condition:
- **onset** is typically `onsetDateTime` → treated as a point interval [datetime, datetime]
- **abatement** is typically `abatementDateTime` or absent
- If the condition is **active** and has no abatement → the interval is open-ended:
  `[onset, null)` meaning it extends from onset indefinitely
- For interval overlap checks, a null end is treated as extending to the maximum date

### Interval Operators
- `overlaps`: two intervals share at least one point. `[A, B] overlaps [C, D]` is true when
  `A <= D and C <= B` (handling null as infinity for open-ended intervals)
- `during`: interval A is completely contained within interval B.
  `A during B` means `start of A >= start of B and end of A <= end of B`
- `during day of`: same as `during` but at day granularity
- Half-open intervals: `[start, start + 6 months)` includes start through the day before
  start + 6 months. For MP starting 2025-01-01, this means [2025-01-01, 2025-07-01),
  i.e., days from Jan 1 through June 30 inclusive.

### Age Calculation
`AgeInYearsAt(date)` computes complete years between birth date and the reference date.
Uses standard birthday calculation: age increments on the birthday each year.

### Population Flow
1. **IPP** (Initial Population): determines eligibility
2. **DENOM** (Denominator): equals IPP
3. **DENEX** (Denominator Exclusions): evaluated only for DENOM members
4. **NUMER** (Numerator): evaluated only for DENOM members NOT in DENEX
5. If DENEX is true → NUMER must be false (patient is excluded from quality calculation)
