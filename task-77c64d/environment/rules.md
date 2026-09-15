# WQX 3.0 Validation Rules

All rules below must be implemented. Each violation produces one error entry with the specified `rule_id` and `category`. When a single element triggers multiple sub-checks (e.g., BR-003 checks two distinct required fields), each missing field is a separate error.

## Business Rules (category: `business_rule`)

### BR-001: Detection Condition Requires Quantitation Limit
When `Result/ResultDescription/ResultDetectionConditionText` has a non-empty value equal to one of:
- `"Not Detected"`
- `"Present Above Quantification Limit"`
- `"Present Below Quantification Limit"`

then `Result/ResultLabInformation/ResultDetectionQuantitationLimit` must be present and must contain both `DetectionQuantitationLimitTypeName` (non-empty) and `DetectionQuantitationLimitMeasure`. One error per violating Result.

### BR-002: Vertical Profile Requires Depth Measures
When `Activity/ActivityDescription/ActivityTypeCode` contains the substring `"Vertical Profile"` (case-sensitive), then `ActivityDescription` must contain both `ActivityTopDepthHeightMeasure` and `ActivityBottomDepthHeightMeasure` elements. Each missing depth element is a separate error (i.e., up to 2 BR-002 errors per Activity).

### BR-003: Tissue Media Requires Biological Identification
When `Activity/ActivityDescription/ActivityMediaName` equals `"Tissue"`, then for each `Result` in that Activity, `Result/BiologicalResultDescription` must be present and must contain:
- `SampleTissueAnatomyName` (non-empty text)
- `SubjectTaxonomicName` (non-empty text)

Each missing required field is a separate error. If `BiologicalResultDescription` is entirely absent, report one BR-003 error for the missing section.

### BR-004: Statistical Base Requires Sample Size
When `Result/ResultDescription/StatisticalBaseCode` is present and non-empty, then `Result/ResultDescription/StatisticalNValueNumeric` must also be present and non-empty. One error per violating Result.

### BR-005: Group Summary Requires Count
When `Result/BiologicalResultDescription/BiologicalIntentName` equals `"Group Summary"`, then `Result/BiologicalResultDescription/GroupSummaryCount` must be present and non-empty. One error per violating Result.

## Domain Value Rules (category: `domain_value`)

### DOM-001: ActivityTypeCode Must Be Valid
`Activity/ActivityDescription/ActivityTypeCode` must match a value in the `Code` column of `/app/domains/ActivityType.csv`. One error per invalid Activity.

### DOM-002: MonitoringLocationTypeName Must Be Valid
`MonitoringLocation/MonitoringLocationIdentity/MonitoringLocationTypeName` must match a value in the `Name` column of `/app/domains/MonitoringLocationType.csv`. One error per invalid MonitoringLocation.

### DOM-003: ActivityMediaName Must Be Valid
`Activity/ActivityDescription/ActivityMediaName` must match a value in the `Name` column of `/app/domains/ActivityMedia.csv`. One error per invalid Activity.

## Referential Integrity Rules (category: `referential_integrity`)

### REF-001: Activity Must Reference Defined MonitoringLocation
`Activity/ActivityDescription/MonitoringLocationIdentifier` must match a `MonitoringLocationIdentifier` defined in a `MonitoringLocation` element within the same `Organization`. One error per invalid Activity reference.

### REF-002: Activity Must Reference Defined Project
`Activity/ActivityDescription/ProjectIdentifier` must match a `ProjectIdentifier` defined in a `Project` element within the same `Organization`. One error per invalid Activity reference.

### REF-003: ActivityGroup Must Reference Defined Activities
Each `ActivityGroup/ActivityIdentifier` element must match an `ActivityIdentifier` from an `Activity` within the same `Organization`. One error per invalid ActivityGroup reference.

## Field Length Rules (category: `field_length`)

Field values that exceed the `maxLength` specified in `/app/constraints.json` produce one error each. The `rule_id` is determined by the field name:

| Field | rule_id |
|-------|---------|
| OrganizationIdentifier | LEN-001 |
| ActivityIdentifier | LEN-002 |
| MonitoringLocationIdentifier | LEN-003 |
| ProjectIdentifier | LEN-004 |
| OrganizationFormalName | LEN-005 |
| MonitoringLocationName | LEN-006 |
| CharacteristicName | LEN-007 |

## XML Namespace

All WQX elements use the namespace `http://www.exchangenetwork.net/schema/wqx/3`. The root element is `WQX` containing a single `Organization`.

## Element Locations in the Hierarchy

```
WQX
  Organization
    OrganizationDescription
      OrganizationIdentifier
      OrganizationFormalName
    Project
      ProjectIdentifier
    MonitoringLocation
      MonitoringLocationIdentity
        MonitoringLocationIdentifier
        MonitoringLocationName
        MonitoringLocationTypeName
    Activity
      ActivityDescription
        ActivityIdentifier
        ActivityTypeCode
        ActivityMediaName
        ActivityStartDate
        ActivityTopDepthHeightMeasure
        ActivityBottomDepthHeightMeasure
        ProjectIdentifier
        MonitoringLocationIdentifier
      Result
        ResultDescription
          ResultDetectionConditionText
          CharacteristicName
          ResultMeasure
          StatisticalBaseCode
          StatisticalNValueNumeric
        BiologicalResultDescription
          BiologicalIntentName
          SubjectTaxonomicName
          SampleTissueAnatomyName
          GroupSummaryCount
        ResultLabInformation
          ResultDetectionQuantitationLimit
            DetectionQuantitationLimitTypeName
            DetectionQuantitationLimitMeasure
    ActivityGroup
      ActivityGroupIdentifier
      ActivityIdentifier
```
