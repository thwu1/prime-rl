CodeSystem: NICUAdmissionReasonCS
Id: nicu-admission-reason-cs
Title: "NICU Admission Reason Code System"
Description: "Reasons for admission to the NICU."
* ^content = #fragment
* #prematurity "Prematurity"
* #low-birth-weight "Low Birth Weight"
* #respiratory-distress "Respiratory Distress"

ValueSet: NICUAdmissionReasonVS
Id: nicu-admission-reason-vs
Title: "NICU Admission Reason Value Set"
Description: "Value set for NICU admission reasons."
* include codes from valueset NICUAdmissionReasonCS
