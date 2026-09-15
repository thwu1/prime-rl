#!/usr/bin/env python3
"""
Generate synthetic DICOM files and FHIR R4 JSON resources for the
DICOM-FHIR conformance audit task.

DICOM files are the ground truth. FHIR resources contain deliberate
discrepancies that the agent must discover and correct.
"""
import json
import os
import warnings

warnings.filterwarnings("ignore")

import pydicom
from pydicom.dataset import Dataset, FileDataset, FileMetaDataset
from pydicom.sequence import Sequence as DicomSequence
from pydicom.uid import ExplicitVRLittleEndian

DICOM_DIR = "/app/dicom_files"
FHIR_DIR = "/app/fhir_resources"
os.makedirs(DICOM_DIR, exist_ok=True)
os.makedirs(FHIR_DIR, exist_ok=True)

IMPL_CLASS_UID = "1.2.826.0.1.3680043.8.499.1"
SC_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.7"  # Secondary Capture


# -- DICOM helpers -----------------------------------------------------

def make_coded_entry(code_value, coding_scheme, code_meaning):
    """Create a DICOM coded entry (CodeSequence item)."""
    ds = Dataset()
    ds.CodeValue = code_value
    ds.CodingSchemeDesignator = coding_scheme
    ds.CodeMeaning = code_meaning
    return ds


def make_dcm(filename, patient_name, patient_id, dob, sex,
             study_uid, study_date, study_desc, accession, modality,
             series_uid, series_desc, series_num, sop_uid,
             anatomic_region=None, procedure_code=None,
             referring_physician=None):
    """Create a DICOM Part 10 file with optional coded sequences."""
    path = os.path.join(DICOM_DIR, filename)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = SC_SOP_CLASS
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = IMPL_CLASS_UID

    ds = FileDataset(path, {}, file_meta=file_meta, preamble=b"\x00" * 128)

    # Patient module
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = dob
    ds.PatientSex = sex

    # Study module
    ds.StudyInstanceUID = study_uid
    ds.StudyDate = study_date
    ds.StudyDescription = study_desc
    ds.AccessionNumber = accession
    ds.StudyID = accession[:8]

    # Series module
    ds.Modality = modality
    ds.SeriesInstanceUID = series_uid
    ds.SeriesDescription = series_desc
    ds.SeriesNumber = series_num

    # SOP Common
    ds.SOPClassUID = SC_SOP_CLASS
    ds.SOPInstanceUID = sop_uid
    ds.InstanceNumber = 1

    # Equipment
    ds.Manufacturer = "SIIM"
    ds.InstitutionName = "SIIM Hospital"

    # Optional coded sequences
    if anatomic_region:
        ds.AnatomicRegionSequence = DicomSequence([
            make_coded_entry(*anatomic_region)
        ])
    if procedure_code:
        ds.ProcedureCodeSequence = DicomSequence([
            make_coded_entry(*procedure_code)
        ])
    if referring_physician:
        ds.ReferringPhysicianName = referring_physician

    ds.save_as(path, write_like_original=False)


# -- Create DICOM files ------------------------------------------------

# Patient 1: Sally SIIM (MRN BreastDx-01-0003)
# Study 1 - Diagnostic Bilateral Mammogram
make_dcm("sally-mammo-cc.dcm",
         "SIIM^Sally", "BreastDx-01-0003", "19500412", "F",
         "1.2.826.0.1.3680043.8.499.4012345001", "20080412",
         "Diagnostic Bilateral Mammogram", "a278028270041068", "MG",
         "1.2.826.0.1.3680043.8.499.4012345001.1", "CC View", 1,
         "1.2.826.0.1.3680043.8.499.4012345001.1.1")

make_dcm("sally-mammo-mlo.dcm",
         "SIIM^Sally", "BreastDx-01-0003", "19500412", "F",
         "1.2.826.0.1.3680043.8.499.4012345001", "20080412",
         "Diagnostic Bilateral Mammogram", "a278028270041068", "MG",
         "1.2.826.0.1.3680043.8.499.4012345001.2", "MLO View", 2,
         "1.2.826.0.1.3680043.8.499.4012345001.2.1")

# Study 2 - Bilateral Breast MRI
make_dcm("sally-mri-t1.dcm",
         "SIIM^Sally", "BreastDx-01-0003", "19500412", "F",
         "1.2.826.0.1.3680043.8.499.4012345002", "20080429",
         "Bilateral Breast MRI", "a085557173658239", "MR",
         "1.2.826.0.1.3680043.8.499.4012345002.1", "T1", 1,
         "1.2.826.0.1.3680043.8.499.4012345002.1.1")

# Patient 2: Ravi SIIM (MRN LIDC-IDRI-0132)
# Study 3 - CT Chest with IV Contrast
make_dcm("ravi-ct-axial.dcm",
         "SIIM^Ravi", "LIDC-IDRI-0132", "19400101", "M",
         "1.2.826.0.1.3680043.8.499.4012345003", "20000101",
         "CT Chest with IV Contrast", "a819497684894126", "CT",
         "1.2.826.0.1.3680043.8.499.4012345003.1", "Axial CT", 1,
         "1.2.826.0.1.3680043.8.499.4012345003.1.1")

make_dcm("ravi-ct-coronal.dcm",
         "SIIM^Ravi", "LIDC-IDRI-0132", "19400101", "M",
         "1.2.826.0.1.3680043.8.499.4012345003", "20000101",
         "CT Chest with IV Contrast", "a819497684894126", "CT",
         "1.2.826.0.1.3680043.8.499.4012345003.2", "Coronal Reformat", 2,
         "1.2.826.0.1.3680043.8.499.4012345003.2.1")

# Patient 3: Joe SIIM (MRN TCGA-17-Z058)
# Study 4 - CT Onco Lung Mass
make_dcm("joe-ct-axial.dcm",
         "SIIM^Joe", "TCGA-17-Z058", "19260101", "M",
         "1.2.826.0.1.3680043.8.499.4012345004", "19860330",
         "CT Onco Lung Mass", "a257132503242682", "CT",
         "1.2.826.0.1.3680043.8.499.4012345004.1", "CT Axial", 1,
         "1.2.826.0.1.3680043.8.499.4012345004.1.1")

# Study 5 - PET Oncologic Study
make_dcm("joe-pet-wb.dcm",
         "SIIM^Joe", "TCGA-17-Z058", "19260101", "M",
         "1.2.826.0.1.3680043.8.499.4012345005", "19860422",
         "PET Oncologic Study", "a819497684894999", "PT",
         "1.2.826.0.1.3680043.8.499.4012345005.1", "PET Whole Body", 1,
         "1.2.826.0.1.3680043.8.499.4012345005.1.1")

make_dcm("joe-pet-ct-atten.dcm",
         "SIIM^Joe", "TCGA-17-Z058", "19260101", "M",
         "1.2.826.0.1.3680043.8.499.4012345005", "19860422",
         "PET Oncologic Study", "a819497684894999", "CT",
         "1.2.826.0.1.3680043.8.499.4012345005.2", "CT Attenuation Correction", 2,
         "1.2.826.0.1.3680043.8.499.4012345005.2.1")

# Patient 4: Kim SIIM (MRN HN-01-0421)
# Full DICOM PN components: Family^Given^Middle^Prefix^Suffix
# Study 6 - MR Head w/o Contrast (2 series)
make_dcm("kim-mr-t1.dcm",
         "SIIM^Kim^Lee^Dr.^Jr.", "HN-01-0421", "19750615", "F",
         "1.2.826.0.1.3680043.8.499.4012345006", "20150615",
         "MR Head w/o Contrast", "a756391024857362", "MR",
         "1.2.826.0.1.3680043.8.499.4012345006.1", "T1 Axial", 1,
         "1.2.826.0.1.3680043.8.499.4012345006.1.1",
         anatomic_region=("69536005", "SCT", "Head structure"),
         procedure_code=("36801-9", "LN", "MR Brain"),
         referring_physician="Smith^Jane")

make_dcm("kim-mr-t2.dcm",
         "SIIM^Kim^Lee^Dr.^Jr.", "HN-01-0421", "19750615", "F",
         "1.2.826.0.1.3680043.8.499.4012345006", "20150615",
         "MR Head w/o Contrast", "a756391024857362", "MR",
         "1.2.826.0.1.3680043.8.499.4012345006.2", "T2 FLAIR", 2,
         "1.2.826.0.1.3680043.8.499.4012345006.2.1",
         anatomic_region=("69536005", "SCT", "Head structure"),
         procedure_code=("36801-9", "LN", "MR Brain"),
         referring_physician="Smith^Jane")


# -- FHIR R4 resource creation (with deliberate discrepancies) ---------

DCM_CODING_SYS = "http://dicom.nema.org/resources/ontology/DCM"
ACSN_TYPE = {
    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0203",
                "code": "ACSN"}]
}


def write_fhir(name, resource):
    path = os.path.join(FHIR_DIR, f"{name}.json")
    with open(path, "w") as f:
        json.dump(resource, f, indent=2)


# -- Patients ----------------------------------------------------------

write_fhir("Patient-sally-siim", {
    "resourceType": "Patient",
    "id": "sally-siim",
    "identifier": [{"system": "urn:oid:1.2.826.0.1.3680043.8.499",
                     "value": "BreastDx-01-0003"}],
    "name": [{"family": "SIIM", "given": ["Sarah"]}],   # DISCREPANCY: Sarah not Sally
    "gender": "female",
    "birthDate": "1950-04-12",
})

write_fhir("Patient-ravi-siim", {
    "resourceType": "Patient",
    "id": "ravi-siim",
    "identifier": [{"system": "urn:oid:1.2.826.0.1.3680043.8.499",
                     "value": "LIDC-IDRI-0132"}],
    "name": [{"family": "SIIM", "given": ["Ravi"]}],
    "gender": "male",
    "birthDate": "1940-01-02",   # DISCREPANCY: should be 1940-01-01
})

write_fhir("Patient-joe-siim", {
    "resourceType": "Patient",
    "id": "joe-siim",
    "identifier": [{"system": "urn:oid:1.2.826.0.1.3680043.8.499",
                     "value": "TCGA-17-Z058"}],
    "name": [{"family": "SIIM", "given": ["Joe"]}],
    "gender": "female",          # DISCREPANCY: should be male
    "birthDate": "1926-01-01",
})

write_fhir("Patient-kim-siim", {
    "resourceType": "Patient",
    "id": "kim-siim",
    "identifier": [{"system": "urn:oid:1.2.826.0.1.3680043.8.499",
                     "value": "HN-01-0421"}],
    "name": [{
        "family": "SIIM",
        "given": ["Kim"],                # DISCREPANCY: missing middle name "Lee"
        "prefix": ["Jr."],               # DISCREPANCY: should be "Dr."
        "suffix": ["Dr."],               # DISCREPANCY: should be "Jr."
    }],
    "gender": "female",
    "birthDate": "1975-06-15",
})


# -- Practitioners -----------------------------------------------------

write_fhir("Practitioner-dr-smith", {
    "resourceType": "Practitioner",
    "id": "dr-smith",
    "name": [{"family": "Smith", "given": ["Jane"]}],
    "qualification": [{"code": {"coding": [
        {"system": "http://terminology.hl7.org/CodeSystem/v2-0360",
         "code": "MD", "display": "Doctor of Medicine"}
    ]}}],
})

write_fhir("Practitioner-dr-wong", {
    "resourceType": "Practitioner",
    "id": "dr-wong",
    "name": [{"family": "Wong", "given": ["David"]}],
    "qualification": [{"code": {"coding": [
        {"system": "http://terminology.hl7.org/CodeSystem/v2-0360",
         "code": "MD", "display": "Doctor of Medicine"}
    ]}}],
})


# -- Imaging Studies ---------------------------------------------------

write_fhir("ImagingStudy-study-sally-mammo", {
    "resourceType": "ImagingStudy",
    "id": "study-sally-mammo",
    "identifier": [
        {"system": "urn:dicom:uid",
         "value": "urn:oid:1.2.826.0.1.3680043.8.499.4012345001"},
        {"type": ACSN_TYPE, "value": "a278028270041068"},
    ],
    "status": "available",
    "subject": {"reference": "Patient/sally-siim"},
    "started": "2008-04-13",    # DISCREPANCY: should be 2008-04-12
    "numberOfSeries": 2,
    "numberOfInstances": 2,
    "modality": [{"system": DCM_CODING_SYS, "code": "MG"}],
    "description": "Diagnostic Bilateral Mammogram",
    "series": [
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345001.1",
            "modality": {"system": DCM_CODING_SYS, "code": "MG"},
            "description": "CC View",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345001.1.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345001.2",
            "modality": {"system": DCM_CODING_SYS, "code": "MG"},
            "description": "MLO View",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345001.2.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
    ],
})

write_fhir("ImagingStudy-study-sally-mri", {
    "resourceType": "ImagingStudy",
    "id": "study-sally-mri",
    "identifier": [
        {"system": "urn:dicom:uid",
         "value": "urn:oid:1.2.826.0.1.3680043.8.499.4012345002"},
        {"type": ACSN_TYPE, "value": "a085557173658239"},
    ],
    "status": "available",
    "subject": {"reference": "Patient/sally-siim"},
    "started": "2008-04-29",
    "numberOfSeries": 1,
    "numberOfInstances": 1,
    "modality": [{"system": DCM_CODING_SYS, "code": "US"}],  # DISCREPANCY: should be MR
    "description": "Bilateral Breast MRI",
    "series": [
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345002.1",
            "modality": {"system": DCM_CODING_SYS, "code": "US"},  # DISCREPANCY: should be MR
            "description": "T1",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345002.1.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
    ],
})

write_fhir("ImagingStudy-study-ravi-ct", {
    "resourceType": "ImagingStudy",
    "id": "study-ravi-ct",
    "identifier": [
        {"system": "urn:dicom:uid",
         "value": "urn:oid:1.2.826.0.1.3680043.8.499.4012345003"},
        {"type": ACSN_TYPE, "value": "a819497684894126"},
    ],
    "status": "available",
    "subject": {"reference": "Patient/ravi-siim"},
    "started": "2000-01-01",
    "numberOfSeries": 1,           # DISCREPANCY: should be 2
    "numberOfInstances": 1,        # DISCREPANCY: should be 2
    "modality": [{"system": DCM_CODING_SYS, "code": "CT"}],
    "description": "CT Chest with IV Contrast",
    "series": [
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345003.1",
            "modality": {"system": DCM_CODING_SYS, "code": "CT"},
            "description": "Axial CT",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345003.1.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
        # DISCREPANCY: series 1.2.826...4012345003.2 (Coronal Reformat) is missing
    ],
})

write_fhir("ImagingStudy-study-joe-ct", {
    "resourceType": "ImagingStudy",
    "id": "study-joe-ct",
    "identifier": [
        {"system": "urn:dicom:uid",
         "value": "urn:oid:1.2.826.0.1.3680043.8.499.4012345004"},
        {"type": ACSN_TYPE, "value": "a257132503242682"},
    ],
    "status": "available",
    "subject": {"reference": "Patient/joe-siim"},
    "started": "1986-03-30",
    "numberOfSeries": 1,
    "numberOfInstances": 1,
    "modality": [{"system": DCM_CODING_SYS, "code": "CT"}],
    "description": "CT Onco Lung Mass",
    "series": [
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345004.1",
            "modality": {"system": DCM_CODING_SYS, "code": "CT"},
            "description": "CT Axial",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345004.1.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
    ],
})

write_fhir("ImagingStudy-study-joe-pet", {
    "resourceType": "ImagingStudy",
    "id": "study-joe-pet",
    "identifier": [
        {"system": "urn:dicom:uid",
         "value": "urn:oid:1.2.826.0.1.3680043.8.499.4012345005"},
        {"type": ACSN_TYPE, "value": "a819497684894126"},  # DISCREPANCY: should be a819497684894999
    ],
    "status": "available",
    "subject": {"reference": "Patient/joe-siim"},
    "started": "1986-04-22",
    "numberOfSeries": 2,
    "numberOfInstances": 3,         # DISCREPANCY: should be 2
    "modality": [
        {"system": DCM_CODING_SYS, "code": "PT"},
        {"system": DCM_CODING_SYS, "code": "CT"},
    ],
    "description": "PET Oncologic Study",
    "series": [
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345005.1",
            "modality": {"system": DCM_CODING_SYS, "code": "PT"},
            "description": "PET Whole Body",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345005.1.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345005.2",
            "modality": {"system": DCM_CODING_SYS, "code": "MR"},  # DISCREPANCY: should be CT
            "description": "CT Attenuation Correction",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345005.2.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
    ],
})

write_fhir("ImagingStudy-study-kim-mr", {
    "resourceType": "ImagingStudy",
    "id": "study-kim-mr",
    "identifier": [
        {"system": "urn:dicom:uid",
         "value": "urn:oid:1.2.826.0.1.3680043.8.499.4012345006"},
        {"type": ACSN_TYPE, "value": "a756391024857362"},
    ],
    "status": "available",
    "subject": {"reference": "Patient/kim-siim"},
    "referrer": {"reference": "Practitioner/dr-wong"},  # DISCREPANCY: DICOM says Smith^Jane = dr-smith
    "started": "2015-06-15",
    "numberOfSeries": 2,
    "numberOfInstances": 2,
    "modality": [{"system": DCM_CODING_SYS, "code": "MR"}],
    "procedureCode": [{"coding": [{
        "system": "http://loinc.org",
        "code": "30799-1",               # DISCREPANCY: should be 36801-9 (MR Brain, not CT Head)
        "display": "CT Head",
    }]}],
    "description": "MR Head w/o Contrast",
    "series": [
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345006.1",
            "modality": {"system": DCM_CODING_SYS, "code": "MR"},
            "bodySite": {
                "system": "http://snomed.info/sct",
                "code": "39607008",              # DISCREPANCY: should be 69536005 (Head, not Lung)
                "display": "Lung structure",
            },
            "description": "T1 Axial",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345006.1.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
        {
            "uid": "1.2.826.0.1.3680043.8.499.4012345006.2",
            "modality": {"system": DCM_CODING_SYS, "code": "MR"},
            "bodySite": {
                "system": "http://snomed.info/sct",
                "code": "39607008",              # DISCREPANCY: should be 69536005
                "display": "Lung structure",
            },
            "description": "T2 FLAIR",
            "numberOfInstances": 1,
            "instance": [{"uid": "1.2.826.0.1.3680043.8.499.4012345006.2.1",
                          "sopClass": {"code": SC_SOP_CLASS}}],
        },
    ],
})


# -- Diagnostic Reports ------------------------------------------------

DX_CODE = {
    "coding": [{"system": "http://loinc.org", "code": "18748-4",
                "display": "Diagnostic imaging study"}]
}

write_fhir("DiagnosticReport-report-joe-ct", {
    "resourceType": "DiagnosticReport",
    "id": "report-joe-ct",
    "status": "final",
    "code": DX_CODE,
    "subject": {"reference": "Patient/ravi-siim"},  # DISCREPANCY: should be Patient/joe-siim
    "effectiveDateTime": "1986-03-30",
    "imagingStudy": [{"reference": "ImagingStudy/study-joe-ct"}],
    "conclusion": "Left hilar mass concerning for malignancy.",
})

write_fhir("DiagnosticReport-report-sally-mammo", {
    "resourceType": "DiagnosticReport",
    "id": "report-sally-mammo",
    "status": "final",
    "code": DX_CODE,
    "subject": {"reference": "Patient/sally-siim"},
    "effectiveDateTime": "2008-04-12",
    "imagingStudy": [{"reference": "ImagingStudy/study-sally-mammo"}],
    "conclusion": "OVERALL BI-RADS 2 (Benign)",
})


print(f"Created {len(os.listdir(DICOM_DIR))} DICOM files in {DICOM_DIR}")
print(f"Created {len(os.listdir(FHIR_DIR))} FHIR resources in {FHIR_DIR}")
