A FHIR Shorthand (FSH) project at `/app/` defines a NICU patient registry. It contains `sushi-config.yaml` and starter `.fsh` files in `input/fsh/` with various defects — some syntactic, some semantic. Additional definitions required by the specification below are missing entirely.

Produce a fully compilable FSH project: running `sushi .` in `/app/` must exit with code 0 and report 0 errors. All artifacts must appear under `/app/fsh-generated/resources/`.

**Required compiled artifacts:**

*Profiles:*
- `StructureDefinition-nicu-patient.json` (Patient): two required extensions for birth weight (Quantity, grams) and gestational age (Quantity, weeks); identifier slicing using pattern-type discriminator on `type` with a mandatory MRN slice (type code `MR` from `http://terminology.hl7.org/CodeSystem/v2-0203`); required `name` (1..\*), `name.family`, `name.given` (1..\*), `birthDate`, `gender`; invariant rejecting future birth dates.
- `StructureDefinition-nicu-admission.json` (Encounter): extensions for admission reason and APGAR scores; subject constrained to the NICU patient profile; encounter class bound at required strength to a NICU encounter class value set; required period with start.
- `StructureDefinition-neonatal-vital-signs.json` (Observation): fixed LOINC code 85353-1; subject constrained to NICU patient profile; `effective[x]` limited to dateTime; pattern-based component slicing with four Quantity-valued slices — heartRate (LOINC 8867-4), respiratoryRate (9279-1), temperature (8310-5), oxygenSaturation (2708-6).

*Extensions:*
- `birth-weight`: Quantity value, UCUM unit `g`, context Patient.
- `gestational-age`: Quantity value, UCUM unit `wk`, context Patient.
- `admission-reason`: CodeableConcept value bound to admission reason value set (extensible), context Encounter.
- `apgar-scores`: complex extension with sub-extensions `oneMinute` and `fiveMinute` (both required, unsignedInt), invariant capping values at 10, context Encounter.

*Terminology:*
- CodeSystem `nicu-admission-reason-cs`: case-sensitive, complete content, minimum 6 codes including `prematurity`, `low-birth-weight`, `respiratory-distress`, `neonatal-jaundice`, `birth-asphyxia`, `congenital-anomaly`.
- ValueSet `nicu-admission-reason-vs`: all codes from the above CodeSystem.
- ValueSet `nicu-encounter-class-vs`: codes `IMP`, `ACUTE`, `EMER` from `http://terminology.hl7.org/CodeSystem/v3-ActCode`.

*Instances:*
- Patient `BabySmithPatient` (nicu-patient): female, born 2024-01-15, MRN "MRN-12345", 1250 g birth weight, 30 wk gestational age.
- Encounter `BabySmithAdmission` (nicu-admission): in-progress, class IMP, references BabySmithPatient, period start 2024-01-15T08:30:00Z, reason `prematurity`, APGAR 1-min 7 / 5-min 9.
- Observation `BabySmithVitals` (neonatal-vital-signs): final, references BabySmithPatient, effective 2024-01-15T10:00:00Z, HR 145/min, RR 52/min, temp 36.8 Cel, SpO2 95%.
