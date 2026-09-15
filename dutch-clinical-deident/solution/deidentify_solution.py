#!/usr/bin/env python3
"""
Solution: Dutch clinical text de-identification pipeline.
Processes clinical notes, detects PHI, writes annotations and redacted text.
"""

import json
import os
import re


def load_list(filepath):
    with open(filepath) as f:
        return [line.strip() for line in f if line.strip()]


def is_valid_bsn(number_str):
    """Validate Dutch BSN using elfproef (11-test)."""
    if len(number_str) != 9 or not number_str.isdigit():
        return False
    digits = [int(d) for d in number_str]
    weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
    total = sum(d * w for d, w in zip(digits, weights))
    return total != 0 and total % 11 == 0


DUTCH_MONTHS = [
    "januari", "februari", "maart", "april", "mei", "juni",
    "juli", "augustus", "september", "oktober", "november", "december",
]

INTERFIXES_SORTED = [
    "van der", "van den", "van de", "van het", "van",
    "de la", "de", "den", "het", "ter", "ten",
]


def find_eponymous_spans(text, diseases):
    spans = []
    sorted_diseases = sorted(diseases, key=len, reverse=True)
    for disease in sorted_diseases:
        for m in re.finditer(re.escape(disease), text, re.IGNORECASE):
            spans.append((m.start(), m.end()))
    return spans


def overlaps_any(start, end, spans):
    for s, e in spans:
        if start < e and end > s:
            return True
    return False


def find_all_annotations(text, patient_meta, first_names, surnames, cities,
                         hospitals, eponymous):
    annotations = []
    epo_spans = find_eponymous_spans(text, eponymous)

    # --- Dates ---
    # dd-mm-yyyy and dd/mm/yyyy
    for m in re.finditer(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b", text):
        annotations.append({
            "text": m.group(), "tag": "datum",
            "start": m.start(), "end": m.end(),
        })
    # d monthname yyyy
    month_re = "|".join(DUTCH_MONTHS)
    for m in re.finditer(
        rf"\b\d{{1,2}}\s+(?:{month_re})\s+\d{{4}}\b", text, re.IGNORECASE
    ):
        annotations.append({
            "text": m.group(), "tag": "datum",
            "start": m.start(), "end": m.end(),
        })

    # --- BSN ---
    for m in re.finditer(r"\b\d{9}\b", text):
        if is_valid_bsn(m.group()):
            annotations.append({
                "text": m.group(), "tag": "bsn",
                "start": m.start(), "end": m.end(),
            })

    # --- Phone numbers ---
    phone_patterns = [
        r"\+31[\s-]?\d{1,3}[\s-]?\d{7,8}",  # international +31
        r"\b06[-\s]?\d{8}\b",                  # mobile 06-
        r"\b0\d{2,3}[-\s]?\d{6,7}\b",         # landline 0XX-
    ]
    seen_phone_spans = set()
    for pp in phone_patterns:
        for m in re.finditer(pp, text):
            span = (m.start(), m.end())
            if not any(
                span[0] < e and span[1] > s for s, e in seen_phone_spans
            ):
                annotations.append({
                    "text": m.group(), "tag": "telefoonnummer",
                    "start": m.start(), "end": m.end(),
                })
                seen_phone_spans.add(span)

    # --- Emails ---
    for m in re.finditer(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", text
    ):
        annotations.append({
            "text": m.group(), "tag": "email",
            "start": m.start(), "end": m.end(),
        })

    # --- URLs ---
    for m in re.finditer(
        r"https?://[a-zA-Z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", text
    ):
        annotations.append({
            "text": m.group(), "tag": "url",
            "start": m.start(), "end": m.end(),
        })

    # --- Patient names from metadata ---
    if patient_meta:
        first_ns = patient_meta.get("first_names", [])
        surname = patient_meta.get("surname", "")
        for fn in first_ns:
            full_name = f"{fn} {surname}"
            for m in re.finditer(r"\b" + re.escape(full_name) + r"\b", text):
                if not overlaps_any(m.start(), m.end(), epo_spans):
                    annotations.append({
                        "text": m.group(), "tag": "naam",
                        "start": m.start(), "end": m.end(),
                    })

    # --- Title + initials + surname patterns ---
    interfix_re = "|".join(re.escape(i) for i in INTERFIXES_SORTED)
    title_pattern = (
        r"(?:prof\.\s+)?"
        r"(?:dr|drs|mr|ir|ing)\.\s+"
        r"(?:[A-Z]\.(?:\s*[A-Z]\.)*\s+)?"
        rf"(?:(?:{interfix_re})\s+)?"
        r"[A-Z][a-zA-Z\u00e0-\u00ff]+"
    )
    for m in re.finditer(title_pattern, text):
        if not overlaps_any(m.start(), m.end(), epo_spans):
            annotations.append({
                "text": m.group(), "tag": "naam",
                "start": m.start(), "end": m.end(),
            })

    # --- Cities ---
    for city in cities:
        for m in re.finditer(r"\b" + re.escape(city) + r"\b", text):
            if not overlaps_any(m.start(), m.end(), epo_spans):
                annotations.append({
                    "text": m.group(), "tag": "locatie",
                    "start": m.start(), "end": m.end(),
                })

    # --- Hospitals ---
    sorted_hospitals = sorted(hospitals, key=len, reverse=True)
    for hospital in sorted_hospitals:
        for m in re.finditer(re.escape(hospital), text):
            annotations.append({
                "text": m.group(), "tag": "instelling",
                "start": m.start(), "end": m.end(),
            })

    return annotations


def resolve_overlaps(annotations):
    if not annotations:
        return []
    # Sort by start, then by length descending
    sorted_anns = sorted(
        annotations, key=lambda a: (a["start"], -(a["end"] - a["start"]))
    )
    resolved = [sorted_anns[0]]
    for ann in sorted_anns[1:]:
        last = resolved[-1]
        if ann["start"] < last["end"]:
            # Overlap: keep the longer one
            if (ann["end"] - ann["start"]) > (last["end"] - last["start"]):
                resolved[-1] = ann
        else:
            resolved.append(ann)
    return resolved


def redact_text(text, annotations):
    sorted_anns = sorted(annotations, key=lambda a: a["start"], reverse=True)
    result = text
    for ann in sorted_anns:
        result = result[: ann["start"]] + f'[{ann["tag"]}]' + result[ann["end"] :]
    return result


def main():
    lookup_dir = "/app/lookup_data"
    first_names = load_list(os.path.join(lookup_dir, "first_names.txt"))
    surnames = load_list(os.path.join(lookup_dir, "surnames.txt"))
    cities = load_list(os.path.join(lookup_dir, "cities.txt"))
    hospitals = load_list(os.path.join(lookup_dir, "hospitals.txt"))
    eponymous = load_list(os.path.join(lookup_dir, "eponymous_diseases.txt"))

    with open("/app/patients.json") as f:
        patients = json.load(f)

    os.makedirs("/app/output", exist_ok=True)

    notes_dir = "/app/clinical_notes"
    for note_file in sorted(os.listdir(notes_dir)):
        if not note_file.endswith(".txt"):
            continue
        note_id = note_file.replace(".txt", "")

        with open(os.path.join(notes_dir, note_file)) as f:
            text = f.read()

        patient_meta = patients.get(note_id, {})

        annotations = find_all_annotations(
            text, patient_meta, first_names, surnames, cities, hospitals, eponymous
        )

        resolved = resolve_overlaps(annotations)
        redacted = redact_text(text, resolved)

        with open(
            os.path.join("/app/output", f"{note_id}_annotations.json"), "w"
        ) as f:
            json.dump(resolved, f, indent=2, ensure_ascii=False)

        with open(os.path.join("/app/output", f"{note_id}_redacted.txt"), "w") as f:
            f.write(redacted)


if __name__ == "__main__":
    main()
