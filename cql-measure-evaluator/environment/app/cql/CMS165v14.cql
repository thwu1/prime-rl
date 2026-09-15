
// CMS165 - Controlling High Blood Pressure
// Adapted from CMS165FHIR v0.5.000 for QICore 6.0.0
// This CQL defines the measure logic that the evaluator must implement.

library CMS165 version '0.5.000'

using QICore version '6.0.0'

include FHIRHelpers version '4.4.000' called FHIRHelpers
include QICoreCommon version '4.0.000' called QICoreCommon

codesystem "LOINC": 'http://loinc.org'
codesystem "ActCode": 'http://terminology.hl7.org/CodeSystem/v3-ActCode'

valueset "Essential Hypertension": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.104.12.1011'
valueset "Office Visit": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1001'
valueset "Annual Wellness Visit": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.1240'
valueset "Preventive Care Services Established Office Visit, 18 and Up": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1025'
valueset "Preventive Care Services Initial Office Visit, 18 and Up": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1023'
valueset "Home Healthcare Services": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1016'
valueset "Outpatient Consultation": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1008'
valueset "Telephone Visits": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1080'
valueset "Emergency Department Visit": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.101.12.1010'
valueset "Encounter Inpatient": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.666.5.307'
valueset "Pregnancy": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.378'
valueset "End Stage Renal Disease": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.353'
valueset "Kidney Transplant Recipient": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1029'
valueset "Chronic Kidney Disease, Stage 5": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.526.3.1002'
valueset "Kidney Transplant": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1012'
valueset "Dialysis Services": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1013'
valueset "ESRD Monthly Outpatient Services": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.109.12.1014'
valueset "Hospice Encounter": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.1003'
valueset "Palliative Care Encounter": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.1167'
valueset "Palliative Care Intervention": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.198.12.1135'
valueset "Frailty Diagnosis": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.113.12.1074'
valueset "Advanced Illness": 'http://cts.nlm.nih.gov/fhir/ValueSet/2.16.840.1.113883.3.464.1003.110.12.1082'

code "Diastolic blood pressure": '8462-4' from "LOINC" display 'Diastolic blood pressure'
code "Systolic blood pressure": '8480-6' from "LOINC" display 'Systolic blood pressure'
code "Blood pressure panel": '85354-9' from "LOINC" display 'Blood pressure panel with all children optional'

parameter "Measurement Period" Interval<DateTime>

context Patient

// ============================================================================
// INITIAL POPULATION
// ============================================================================

define "Initial Population":
  AgeInYearsAt(date from end of "Measurement Period") in Interval[18, 85]
    and exists "Essential Hypertension Diagnosis"
    and exists "Qualifying Encounters"

// Hypertension must be active and have onset overlapping the first 6 months of the MP
define "Essential Hypertension Diagnosis":
  ( [Condition: "Essential Hypertension"] ) Hypertension
    where Hypertension.isActive()
      and Hypertension.isConfirmedOrUnspecified()
      and Hypertension.prevalenceInterval() overlaps Interval[start of "Measurement Period", start of "Measurement Period" + 6 months)

define "Qualifying Encounters":
  ( [Encounter: "Office Visit"]
      union [Encounter: "Annual Wellness Visit"]
      union [Encounter: "Preventive Care Services Established Office Visit, 18 and Up"]
      union [Encounter: "Preventive Care Services Initial Office Visit, 18 and Up"]
      union [Encounter: "Home Healthcare Services"]
      union [Encounter: "Outpatient Consultation"]
      union [Encounter: "Telephone Visits"]
  ) ValidEncounter
    where ValidEncounter.period during "Measurement Period"
      and ValidEncounter.status = 'finished'

// ============================================================================
// DENOMINATOR
// ============================================================================

define "Denominator":
  "Initial Population"

// ============================================================================
// DENOMINATOR EXCLUSIONS
// ============================================================================

define "Denominator Exclusions":
  "Has Hospice Services"
    or exists "Pregnancy or Renal Diagnosis Exclusions"
    or exists "End Stage Renal Disease Procedures"
    or exists "End Stage Renal Disease Encounter"
    or "Has Palliative Care in the Measurement Period"
    or "Is Age 66 to 80 with Advanced Illness and Frailty"
    or "Is Age 81 or Older with Frailty"

define "Has Hospice Services":
  exists (
    [Encounter: "Hospice Encounter"] HospiceEnc
      where HospiceEnc.period overlaps "Measurement Period"
  )

define "Pregnancy or Renal Diagnosis Exclusions":
  ( [Condition: "Pregnancy"]
      union [Condition: "End Stage Renal Disease"]
      union [Condition: "Kidney Transplant Recipient"]
      union [Condition: "Chronic Kidney Disease, Stage 5"]
  ) ExclusionDiagnosis
    where ExclusionDiagnosis.prevalenceInterval() overlaps "Measurement Period"

define "End Stage Renal Disease Procedures":
  ( [Procedure: "Kidney Transplant"]
      union [Procedure: "Dialysis Services"]
  ) ESRDProcedure
    where ESRDProcedure.status = 'completed'
      and end of ESRDProcedure.performed.toInterval() on or before end of "Measurement Period"

define "End Stage Renal Disease Encounter":
  ( [Encounter: "ESRD Monthly Outpatient Services"] ) ESRDEncounter
    where ESRDEncounter.status = 'finished'
      and ESRDEncounter.period starts on or before end of "Measurement Period"

define "Has Palliative Care in the Measurement Period":
  exists (
    ( [Encounter: "Palliative Care Encounter"]
        union [Encounter: "Palliative Care Intervention"]
    ) PalliativeEnc
      where PalliativeEnc.period overlaps "Measurement Period"
  )

// Age 66-80: requires BOTH advanced illness AND frailty diagnosis
define "Is Age 66 to 80 with Advanced Illness and Frailty":
  AgeInYearsAt(date from end of "Measurement Period") in Interval[66, 80]
    and exists (
      [Condition: "Frailty Diagnosis"] FrailtyDx
        where FrailtyDx.prevalenceInterval() overlaps Interval[start of "Measurement Period" - 1 year, end of "Measurement Period"]
    )
    and exists (
      [Condition: "Advanced Illness"] AdvIllness
        where AdvIllness.prevalenceInterval() overlaps Interval[start of "Measurement Period" - 1 year, end of "Measurement Period"]
    )

// Age 81+: requires only frailty diagnosis
define "Is Age 81 or Older with Frailty":
  AgeInYearsAt(date from end of "Measurement Period") >= 81
    and exists (
      [Condition: "Frailty Diagnosis"] FrailtyDx
        where FrailtyDx.prevalenceInterval() overlaps Interval[start of "Measurement Period" - 1 year, end of "Measurement Period"]
    )

// ============================================================================
// NUMERATOR
// ============================================================================

define "Numerator":
  "Lowest Systolic Reading on Most Recent Blood Pressure Day" < 140 'mm[Hg]'
    and "Lowest Diastolic Reading on Most Recent Blood Pressure Day" < 90 'mm[Hg]'

// A blood pressure observation is qualifying if:
// 1. It is a USCoreBloodPressureProfile observation (code = LOINC 85354-9)
// 2. Its status is 'final', 'amended', or 'corrected'
// 3. It was NOT taken during an ED or Inpatient encounter
//    (determined by checking encounter class OR by checking if a disqualifying
//     encounter exists on the same day)

define "Qualifying Systolic Blood Pressure Reading":
  ( [Observation: "Blood pressure panel"] BloodPressure
      where BloodPressure.status in { 'final', 'amended', 'corrected' }
        and not BloodPressure.isDuringEDorInpatient()
        and BloodPressure.effective.latest() during day of "Measurement Period"
        and exists (
          BloodPressure.component SystolicBP
            where SystolicBP.code ~ "Systolic blood pressure"
              and SystolicBP.value is not null
        )
  )

define "Qualifying Diastolic Blood Pressure Reading":
  ( [Observation: "Blood pressure panel"] BloodPressure
      where BloodPressure.status in { 'final', 'amended', 'corrected' }
        and not BloodPressure.isDuringEDorInpatient()
        and BloodPressure.effective.latest() during day of "Measurement Period"
        and exists (
          BloodPressure.component DiastolicBP
            where DiastolicBP.code ~ "Diastolic blood pressure"
              and DiastolicBP.value is not null
        )
  )

// isDuringEDorInpatient checks:
// 1. If the observation has an encounter reference, resolve it
// 2. If the referenced encounter's class is in {EMER, IMP, ACUTE, NONAC, PRENC, SS}
//    then the observation is disqualified
// 3. OR if a standalone ED/Inpatient encounter exists on the same day as the observation
define fluent function isDuringEDorInpatient(observation Observation):
  exists (
    ( [Encounter: "Encounter Inpatient"]
        union [Encounter: "Emergency Department Visit"]
    ) DisqualifyingEncounter
      where DisqualifyingEncounter.status = 'finished'
        and observation.effective.latest() during day of DisqualifyingEncounter.period
  )
  or (observation.encounter is not null
      and (observation.encounter.getEncounter()).class.code
            in { 'EMER', 'IMP', 'ACUTE', 'NONAC', 'PRENC', 'SS' })

define fluent function getEncounter(reference Reference):
  singleton from (
    [Encounter] E where E.id = reference.reference.getId()
  )

// Blood Pressure Days: dates that have BOTH a qualifying systolic AND diastolic reading
define "Blood Pressure Days":
  ( "Qualifying Diastolic Blood Pressure Reading" DBPExam
      return date from DBPExam.effective.latest()
  )
    intersect ( "Qualifying Systolic Blood Pressure Reading" SBPExam
        return date from SBPExam.effective.latest()
    )

// Most Recent Blood Pressure Day: the latest date from Blood Pressure Days
define "Most Recent Blood Pressure Day":
  Last("Blood Pressure Days" BPDays sort asc)

// Lowest systolic reading on the most recent BP day
define "Lowest Systolic Reading on Most Recent Blood Pressure Day":
  First(
    "Qualifying Systolic Blood Pressure Reading" SBPReading
      where date from SBPReading.effective.latest() = "Most Recent Blood Pressure Day"
      return singleton from (
        SBPReading.component SBPComponent
          where SBPComponent.code ~ "Systolic blood pressure"
          return SBPComponent.value as Quantity
      )
      sort asc
  )

// Lowest diastolic reading on the most recent BP day
define "Lowest Diastolic Reading on Most Recent Blood Pressure Day":
  First(
    "Qualifying Diastolic Blood Pressure Reading" DBPReading
      where date from DBPReading.effective.latest() = "Most Recent Blood Pressure Day"
      return singleton from (
        DBPReading.component DBPComponent
          where DBPComponent.code ~ "Diastolic blood pressure"
          return DBPComponent.value as Quantity
      )
      sort asc
  )

// ============================================================================
// HELPER FUNCTIONS (from QICoreCommon)
// ============================================================================

// isActive(): returns true if clinicalStatus is 'active', 'recurrence', or 'relapse'
define fluent function isActive(condition Condition):
  condition.clinicalStatus ~ "active"
    or condition.clinicalStatus ~ "recurrence"
    or condition.clinicalStatus ~ "relapse"

// isConfirmedOrUnspecified(): returns true if verificationStatus is 'confirmed',
// 'provisional', 'differential', or absent (null)
define fluent function isConfirmedOrUnspecified(condition Condition):
  condition.verificationStatus is null
    or condition.verificationStatus ~ "confirmed"
    or condition.verificationStatus ~ "provisional"
    or condition.verificationStatus ~ "differential"

// prevalenceInterval(): returns the interval from condition onset to abatement.
// For active conditions with no abatement, the interval is open-ended (extends to infinity).
// onset is normalized via toInterval() — if it's a DateTime, it becomes [DateTime, DateTime].
define fluent function prevalenceInterval(condition Condition):
  if condition.isActive() then
    Interval[start of condition.onset.toInterval(), end of condition.abatementInterval()]
  else
    (end of condition.abatementInterval()) abatementDate
      return if abatementDate is null then
        Interval[start of condition.onset.toInterval(), abatementDate)
      else
        Interval[start of condition.onset.toInterval(), abatementDate]

// toInterval(): normalizes a choice type to an interval.
// DateTime → [DateTime, DateTime]
// Interval<DateTime> → itself
define fluent function toInterval(choice Choice<DateTime, Interval<DateTime>>):
  case
    when choice is DateTime then Interval[choice as DateTime, choice as DateTime]
    when choice is Interval<DateTime> then choice as Interval<DateTime>
    else null as Interval<DateTime>
  end

// latest(): given a choice type, returns the ending point of its interval
// (or start if no end). Used to extract effective date from observations.
define fluent function latest(choice Choice<DateTime, Interval<DateTime>>):
  end of choice.toInterval()

// getId(): returns the tail of a URI (everything after the last '/')
define fluent function getId(uri String):
  Last(Split(uri, '/'))
