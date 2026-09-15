#!/usr/bin/env python3
"""
Generate all FSH files for the NICU patient registry IG.
Fixes bugs in existing files and creates all missing definitions.
"""

import os

FSH_DIR = "/app/input/fsh"


def write_fsh(filename, content):
    filepath = os.path.join(FSH_DIR, filename)
    with open(filepath, "w") as f:
        f.write(content.lstrip("\n"))
    print(f"Wrote {filepath}")


# 1. Fix aliases.fsh - add missing UCUM, V3ActCode, and identifier type aliases
write_fsh("aliases.fsh", """
Alias: LNC = http://loinc.org
Alias: SCT = http://snomed.info/sct
Alias: UCUM = http://unitsofmeasure.org
Alias: V3ACT = http://terminology.hl7.org/CodeSystem/v3-ActCode
Alias: IDTYPE = http://terminology.hl7.org/CodeSystem/v2-0203
""")

# 2. Fix rulesets.fsh - add missing ^ prefix on ExtensionContext caret paths
write_fsh("rulesets.fsh", """
RuleSet: ExtensionContext(path)
* ^context[+].type = #element
* ^context[=].expression = "{path}"

RuleSet: DocumentExtension(path, short, definition)
* extension[{path}] ^short = {short}
* extension[{path}] ^definition = {definition}

RuleSet: CommonNICUObservationRules
* status MS
* code MS
* subject MS
* effective[x] MS
""")

# 3. Create extensions.fsh
write_fsh("extensions.fsh", """
Extension: BirthWeight
Id: birth-weight
Title: "Birth Weight"
Description: "The weight of the neonate at birth in grams."
* insert ExtensionContext(Patient)
* value[x] only Quantity
* valueQuantity = UCUM#g

Extension: GestationalAge
Id: gestational-age
Title: "Gestational Age"
Description: "Gestational age at birth in completed weeks."
* insert ExtensionContext(Patient)
* value[x] only Quantity
* valueQuantity = UCUM#wk

Extension: AdmissionReason
Id: admission-reason
Title: "NICU Admission Reason"
Description: "The primary reason for NICU admission."
* insert ExtensionContext(Encounter)
* value[x] only CodeableConcept
* valueCodeableConcept from NICUAdmissionReasonVS (extensible)

Extension: APGARScores
Id: apgar-scores
Title: "APGAR Scores"
Description: "APGAR scores at 1 and 5 minutes after birth."
* insert ExtensionContext(Encounter)
* obeys apgar-range
* extension contains
    oneMinute 1..1 MS and
    fiveMinute 1..1 MS
* extension[oneMinute].value[x] only unsignedInt
* extension[fiveMinute].value[x] only unsignedInt
* insert DocumentExtension(oneMinute, "1-minute APGAR score", "APGAR score assessed at 1 minute after birth")
* insert DocumentExtension(fiveMinute, "5-minute APGAR score", "APGAR score assessed at 5 minutes after birth")
""")

# 4. Create profiles.fsh
write_fsh("profiles.fsh", """
Profile: NICUPatient
Parent: Patient
Id: nicu-patient
Title: "NICU Patient"
Description: "A patient profile for neonates admitted to the NICU."
* obeys nicu-1
* extension contains
    BirthWeight named birthWeight 1..1 MS and
    GestationalAge named gestationalAge 1..1 MS
* identifier ^slicing.discriminator.type = #pattern
* identifier ^slicing.discriminator.path = "type"
* identifier ^slicing.rules = #open
* identifier contains MRN 1..1 MS
* identifier[MRN].type = IDTYPE#MR
* identifier[MRN].system 1..1 MS
* identifier[MRN].value 1..1 MS
* name 1..* MS
* name.family 1..1 MS
* name.given 1..* MS
* birthDate 1..1 MS
* gender 1..1 MS

Profile: NICUAdmission
Parent: Encounter
Id: nicu-admission
Title: "NICU Admission"
Description: "An encounter profile for NICU admissions."
* extension contains
    AdmissionReason named admissionReason 1..1 MS and
    APGARScores named apgarScores 0..1 MS
* status MS
* class MS
* class from NICUEncounterClassVS (required)
* subject 1..1 MS
* subject only Reference(NICUPatient)
* period 1..1 MS
* period.start 1..1 MS

Profile: NeonatalVitalSigns
Parent: Observation
Id: neonatal-vital-signs
Title: "Neonatal Vital Signs Panel"
Description: "A panel observation for recording neonatal vital signs."
* insert CommonNICUObservationRules
* code = LNC#85353-1 "Vital signs, weight, height, head circumference, oxygen saturation and BMI panel"
* subject 1..1 MS
* subject only Reference(NICUPatient)
* effective[x] only dateTime
* component ^slicing.discriminator.type = #pattern
* component ^slicing.discriminator.path = "code"
* component ^slicing.rules = #open
* component contains
    heartRate 0..1 MS and
    respiratoryRate 0..1 MS and
    temperature 0..1 MS and
    oxygenSaturation 0..1 MS
* component[heartRate].code = LNC#8867-4 "Heart rate"
* component[heartRate].value[x] only Quantity
* component[respiratoryRate].code = LNC#9279-1 "Respiratory rate"
* component[respiratoryRate].value[x] only Quantity
* component[temperature].code = LNC#8310-5 "Body temperature"
* component[temperature].value[x] only Quantity
* component[oxygenSaturation].code = LNC#2708-6 "Oxygen saturation in Arterial blood"
* component[oxygenSaturation].value[x] only Quantity
""")

# 5. Create terminology.fsh
write_fsh("terminology.fsh", """
CodeSystem: NICUAdmissionReasonCS
Id: nicu-admission-reason-cs
Title: "NICU Admission Reason Code System"
Description: "Reasons for admission to the NICU."
* ^caseSensitive = true
* ^content = #complete
* #prematurity "Prematurity" "Birth before 37 completed weeks of gestation"
* #low-birth-weight "Low Birth Weight" "Birth weight less than 2500 grams"
* #respiratory-distress "Respiratory Distress" "Respiratory distress syndrome or other breathing difficulties"
* #neonatal-jaundice "Neonatal Jaundice" "Pathological jaundice requiring phototherapy"
* #birth-asphyxia "Birth Asphyxia" "Oxygen deprivation during birth"
* #congenital-anomaly "Congenital Anomaly" "Congenital malformation or chromosomal abnormality"
* #neonatal-sepsis "Neonatal Sepsis" "Suspected or confirmed neonatal infection"
* #hypoglycemia "Hypoglycemia" "Low blood glucose in the newborn"

ValueSet: NICUAdmissionReasonVS
Id: nicu-admission-reason-vs
Title: "NICU Admission Reason Value Set"
Description: "Value set for NICU admission reasons."
* include codes from system NICUAdmissionReasonCS

ValueSet: NICUEncounterClassVS
Id: nicu-encounter-class-vs
Title: "NICU Encounter Class Value Set"
Description: "Encounter class codes applicable to NICU encounters."
* V3ACT#IMP "inpatient encounter"
* V3ACT#ACUTE "inpatient acute"
* V3ACT#EMER "emergency"
""")

# 6. Create invariants.fsh
write_fsh("invariants.fsh", """
Invariant: nicu-1
Description: "Birth date must not be in the future"
Expression: "birthDate <= today()"
Severity: #error

Invariant: apgar-range
Description: "APGAR scores must not exceed 10"
Expression: "extension.all(value.ofType(unsignedInt).empty() or value.ofType(unsignedInt) <= 10)"
Severity: #error
""")

# 7. Create instances.fsh
write_fsh("instances.fsh", """
Instance: BabySmithPatient
InstanceOf: NICUPatient
Description: "Example NICU Patient - Baby Smith"
* identifier[MRN].system = "http://hospital.example.org/mrn"
* identifier[MRN].value = "MRN-12345"
* name.family = "Smith"
* name.given = "Baby"
* birthDate = "2024-01-15"
* gender = #female
* extension[birthWeight].valueQuantity = 1250 'g'
* extension[gestationalAge].valueQuantity = 30 'wk'

Instance: BabySmithAdmission
InstanceOf: NICUAdmission
Description: "Example NICU Admission for Baby Smith"
* status = #in-progress
* class = V3ACT#IMP "inpatient encounter"
* subject = Reference(BabySmithPatient)
* period.start = "2024-01-15T08:30:00Z"
* extension[admissionReason].valueCodeableConcept = NICUAdmissionReasonCS#prematurity "Prematurity"
* extension[apgarScores].extension[oneMinute].valueUnsignedInt = 7
* extension[apgarScores].extension[fiveMinute].valueUnsignedInt = 9

Instance: BabySmithVitals
InstanceOf: NeonatalVitalSigns
Description: "Example Vital Signs for Baby Smith"
* status = #final
* code = LNC#85353-1 "Vital signs, weight, height, head circumference, oxygen saturation and BMI panel"
* subject = Reference(BabySmithPatient)
* effectiveDateTime = "2024-01-15T10:00:00Z"
* component[heartRate].code = LNC#8867-4 "Heart rate"
* component[heartRate].valueQuantity = 145 '/min'
* component[respiratoryRate].code = LNC#9279-1 "Respiratory rate"
* component[respiratoryRate].valueQuantity = 52 '/min'
* component[temperature].code = LNC#8310-5 "Body temperature"
* component[temperature].valueQuantity = 36.8 'Cel'
* component[oxygenSaturation].code = LNC#2708-6 "Oxygen saturation in Arterial blood"
* component[oxygenSaturation].valueQuantity = 95 '%'
""")

print("All FSH files generated successfully.")
