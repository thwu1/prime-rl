#!/usr/bin/env python3
"""Generate synthetic DICOM Part-10 files for the FHIR-DICOM reconciliation task."""
import os
import pydicom
from pydicom.dataset import Dataset, FileDataset
from pydicom.uid import ExplicitVRLittleEndian
from pydicom.sequence import Sequence


def create_dicom(
    patient_name, patient_id, patient_dob, patient_sex,
    study_uid, study_date, study_desc, accession, referring_physician,
    series_uid, series_number, modality,
    sop_uid, instance_number, output_path,
    procedure_codes=None
):
    file_meta = Dataset()
    file_meta.FileMetaInformationVersion = b'\x00\x01'
    file_meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.7'
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = '1.2.826.0.1.3680043.8.498.1'
    file_meta.ImplementationVersionName = 'SIIM_SYNTH'

    ds = FileDataset(
        output_path, {}, preamble=b"\x00" * 128, file_meta=file_meta,
        is_implicit_VR=False, is_little_endian=True
    )

    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.PatientBirthDate = patient_dob
    ds.PatientSex = patient_sex

    ds.StudyInstanceUID = study_uid
    ds.StudyDate = study_date
    ds.StudyTime = '120000'
    ds.StudyDescription = study_desc
    ds.AccessionNumber = accession
    ds.ReferringPhysicianName = referring_physician
    ds.StudyID = '1'

    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.Modality = modality
    ds.SeriesDescription = f'{modality} Series {series_number}'

    ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.7'
    ds.SOPInstanceUID = sop_uid
    ds.InstanceNumber = instance_number

    # Add Procedure Code Sequence (SQ VR) if provided
    if procedure_codes:
        proc_seq = Sequence()
        for pc in procedure_codes:
            item = Dataset()
            item.CodeValue = pc['code']
            item.CodingSchemeDesignator = pc['scheme']
            item.CodeMeaning = pc['meaning']
            proc_seq.append(item)
        ds.ProcedureCodeSequence = proc_seq

    ds.Rows = 4
    ds.Columns = 4
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.PixelData = bytes([128] * 16)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    ds.save_as(output_path)


# Ground truth patient/study/series/instance data
patients = [
    {
        'name': 'SIIM^SALLY', 'id': 'BreastDx-01-0003',
        'dob': '19500412', 'sex': 'F',
        'studies': [
            {
                'uid': '1.2.826.0.1.3680043.8.498.46981922031143',
                'date': '20080412',
                'desc': 'Diagnostic Bilateral Mammogram',
                'accession': 'a278028270041068',
                'referrer': 'REFERRING^MOHAN',
                'procedure_codes': [
                    {'code': '71651007', 'scheme': 'SCT', 'meaning': 'Mammography'}
                ],
                'series': [
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.81019372210938',
                        'num': 1, 'mod': 'MG',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.91019372210001', 1),
                            ('1.2.826.0.1.3680043.8.498.91019372210002', 2),
                        ]
                    },
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.81019372210939',
                        'num': 2, 'mod': 'MG',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.91019372210003', 1),
                            ('1.2.826.0.1.3680043.8.498.91019372210004', 2),
                        ]
                    },
                ]
            }
        ]
    },
    {
        'name': 'SIIM^JOE', 'id': 'TCGA-17-Z058',
        'dob': '19260401', 'sex': 'M',
        'studies': [
            {
                'uid': '1.2.826.0.1.3680043.8.498.93853029328343',
                'date': '19860330',
                'desc': 'CT Onco Lung Mass',
                'accession': 'a257132503242682',
                'referrer': 'REFERRING^MD',
                'procedure_codes': [
                    {'code': '75385009', 'scheme': 'SCT', 'meaning': 'Computed tomography'}
                ],
                'series': [
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.82764519203847',
                        'num': 1, 'mod': 'CT',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.92764519203001', 1),
                            ('1.2.826.0.1.3680043.8.498.92764519203002', 2),
                            ('1.2.826.0.1.3680043.8.498.92764519203003', 3),
                        ]
                    },
                ]
            }
        ]
    },
    {
        'name': 'SIIM^ANDY', 'id': 'TCGA-50-5072',
        'dob': '19250101', 'sex': 'M',
        'studies': [
            {
                'uid': '1.2.826.0.1.3680043.8.498.45678901234567',
                'date': '20000128',
                'desc': 'CT Chest Without Contrast',
                'accession': 'a508258761846499',
                'referrer': 'SMITH^JOHN^DR',
                'procedure_codes': None,
                'series': [
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.83456789012345',
                        'num': 1, 'mod': 'CT',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.93456789012001', 1),
                            ('1.2.826.0.1.3680043.8.498.93456789012002', 2),
                        ]
                    },
                ]
            }
        ]
    },
    {
        'name': 'SIIM^RAVI', 'id': 'LIDC-IDRI-0132',
        'dob': '19400101', 'sex': 'M',
        'studies': [
            {
                'uid': '1.2.826.0.1.3680043.8.498.12345678901234',
                'date': '20000101',
                'desc': 'CT Chest with IV Contrast',
                'accession': 'a819497684894126',
                'referrer': 'PATEL^ARUN^DR',
                'procedure_codes': [
                    {'code': '75385009', 'scheme': 'SCT', 'meaning': 'Computed tomography'}
                ],
                'series': [
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.22345678901234',
                        'num': 1, 'mod': 'CT',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.32345678901001', 1),
                            ('1.2.826.0.1.3680043.8.498.32345678901002', 2),
                            ('1.2.826.0.1.3680043.8.498.32345678901003', 3),
                        ]
                    },
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.22345678901235',
                        'num': 2, 'mod': 'CT',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.32345678901004', 1),
                        ]
                    },
                ]
            },
            {
                'uid': '1.2.826.0.1.3680043.8.498.12345678905678',
                'date': '20000101',
                'desc': 'Chest PA Radiograph',
                'accession': 'a819497684894127',
                'referrer': 'PATEL^ARUN^DR',
                'procedure_codes': None,
                'series': [
                    {
                        'uid': '1.2.826.0.1.3680043.8.498.22345678905678',
                        'num': 1, 'mod': 'CR',
                        'instances': [
                            ('1.2.826.0.1.3680043.8.498.32345678905001', 1),
                        ]
                    },
                ]
            }
        ]
    },
]

base_dir = '/app/dicom_studies'
for p in patients:
    pdir = p['name'].replace('^', '_').lower()
    for s in p['studies']:
        for series in s['series']:
            for sop_uid, inst_num in series['instances']:
                path = os.path.join(
                    base_dir, pdir,
                    f"study_{s['accession']}",
                    f"series_{series['num']}",
                    f"instance_{inst_num}.dcm"
                )
                create_dicom(
                    p['name'], p['id'], p['dob'], p['sex'],
                    s['uid'], s['date'], s['desc'], s['accession'], s['referrer'],
                    series['uid'], series['num'], series['mod'],
                    sop_uid, inst_num, path,
                    procedure_codes=s.get('procedure_codes')
                )
                print(f"Created: {path}")

print("DICOM data generation complete.")
