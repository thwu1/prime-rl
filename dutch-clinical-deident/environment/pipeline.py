#!/usr/bin/env python3
"""
Dutch clinical text de-identification pipeline using docdeid framework.
Known issues: produces incorrect output on clinical notes.
"""

import json
import os

from docdeid import DocDeid
from docdeid.process import RegexpAnnotator, SimpleRedactor
from docdeid.tokenize import WordBoundaryTokenizer


def create_pipeline():
    deidentifier = DocDeid()
    deidentifier.tokenizers["default"] = WordBoundaryTokenizer()

    # Date detector
    deidentifier.processors.add_processor(
        "dates",
        RegexpAnnotator(regexp_pattern=r"\b\d{2}-\d{2}-\d{4}\b", tag="datum"),
    )

    # BSN detector
    deidentifier.processors.add_processor(
        "bsn",
        RegexpAnnotator(regexp_pattern=r"\b\d{9}\b", tag="bsn"),
    )

    # Redactor
    deidentifier.processors.add_processor("redactor", SimpleRedactor())

    return deidentifier


def main():
    deidentifier = create_pipeline()

    with open("/app/patients.json") as f:
        patients = json.load(f)

    os.makedirs("/app/output", exist_ok=True)

    for note_file in sorted(os.listdir("/app/clinical_notes")):
        if not note_file.endswith(".txt"):
            continue
        note_id = note_file.replace(".txt", "")

        with open(f"/app/clinical_notes/{note_file}") as f:
            text = f.read()

        patient_meta = patients.get(note_id, {})
        doc = deidentifier.deidentify(text, metadata={"patient": patient_meta})

        ann_list = []
        for ann in doc.annotations:
            ann_list.append(
                {
                    "text": ann.text,
                    "tag": ann.tag,
                    "start": ann.start_char,
                    "end": ann.end_char,
                }
            )
        ann_list.sort(key=lambda a: a["start"])

        with open(f"/app/output/{note_id}_annotations.json", "w") as f:
            json.dump(ann_list, f, indent=2, ensure_ascii=False)

        with open(f"/app/output/{note_id}_redacted.txt", "w") as f:
            f.write(doc.deidentified_text or text)


if __name__ == "__main__":
    main()
