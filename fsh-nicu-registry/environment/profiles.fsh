Profile: NICUPatient
Parent: Patient
Id: nicu-patient
Title: "NICU Patient"
Description: "A patient profile for neonates admitted to the NICU."
* extension contains
    BirthWeight named birthWeight 1..1 MS and
    GestationalAge named gestationalAge 1..1 MS
* identifier ^slicing.discriminator[0].type = #value
* identifier ^slicing.discriminator[0].path = "type"
* identifier ^slicing.rules = #open
* identifier contains MRN 1..1 MS
* identifier[MRN].type = IDTYPE#MR
* identifier[MRN].system 1..1 MS
* identifier[MRN].value 1..1 MS
* name 1..* MS
* name.family 1..1 MS
* name.given 1..* MS

Profile: NICUAdmission
Parent: Encounter
Id: nicu-admission
Title: "NICU Admission"
Description: "An encounter profile for NICU admissions."
* status MS
* class MS
* subject 1..1 MS
* period 1..1 MS
* period.start 1..1 MS
