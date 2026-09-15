#!/usr/bin/env python3
"""
Dutch clinical text de-identification pipeline using docdeid.
Usage: python3 pipeline.py <input_file> <patient_id> [output_dir]
"""

import json
import os
import re
import sys
from pathlib import Path

from docdeid import DocDeid
from docdeid.annotation import Annotation, AnnotationSet
from docdeid.process.annotator import (
    Annotator,
    RegexpAnnotator,
    SingleTokenLookupAnnotator,
    MultiTokenLookupAnnotator,
)
from docdeid.process.doc_processor import DocProcessor
from docdeid.process.redactor import SimpleRedactor
from docdeid.tokenizer import WordBoundaryTokenizer
from docdeid.str.processor import LowercaseString


# ---------------------------------------------------------------------------
# Custom annotators
# ---------------------------------------------------------------------------

class BsnAnnotator(Annotator):
    """Detects valid Dutch BSN numbers using elfproef (11-test) validation."""

    def __init__(self, bsn_regexp, *args, capture_group=0, **kwargs):
        self.bsn_regexp = re.compile(bsn_regexp)
        self.capture_group = capture_group
        super().__init__(*args, **kwargs)

    @staticmethod
    def _elfproef(bsn):
        """Return True if *bsn* (a 9-digit string) passes the elfproef."""
        if len(bsn) != 9 or any(not c.isdigit() for c in bsn):
            return False
        total = sum(int(c) * f for c, f in zip(bsn, [9, 8, 7, 6, 5, 4, 3, 2, -1]))
        return total % 11 == 0 and total != 0

    def annotate(self, doc):
        annotations = []
        for match in self.bsn_regexp.finditer(doc.text):
            text = match.group(self.capture_group)
            digits = re.sub(r"\D", "", text)
            if self._elfproef(digits):
                start, end = match.span(self.capture_group)
                annotations.append(
                    Annotation(
                        text=text,
                        start_char=start,
                        end_char=end,
                        tag=self.tag,
                        priority=self.priority,
                    )
                )
        return annotations


class PhoneNumberAnnotator(Annotator):
    """Detects Dutch phone numbers with digit-count validation."""

    def __init__(self, phone_regexp, *args, min_digits=9, max_digits=11, **kwargs):
        self.phone_regexp = re.compile(phone_regexp)
        self.min_digits = min_digits
        self.max_digits = max_digits
        super().__init__(*args, **kwargs)

    def annotate(self, doc):
        annotations = []
        for match in self.phone_regexp.finditer(doc.text):
            text = match.group(0)
            digits = re.sub(r"\D", "", text)
            if self.min_digits <= len(digits) <= self.max_digits:
                annotations.append(
                    Annotation(
                        text=text,
                        start_char=match.start(),
                        end_char=match.end(),
                        tag=self.tag,
                        priority=self.priority,
                    )
                )
        return annotations


# ---------------------------------------------------------------------------
# Custom doc-processors
# ---------------------------------------------------------------------------

class MedicalTermFilter(DocProcessor):
    """Remove annotations whose spans fall inside a known medical term."""

    def __init__(self, medical_terms):
        self.medical_terms = medical_terms

    def process(self, doc, **kwargs):
        text_lower = doc.text.lower()
        spans = []
        for term in self.medical_terms:
            tl = term.lower()
            idx = 0
            while idx <= len(text_lower) - len(tl):
                pos = text_lower.find(tl, idx)
                if pos == -1:
                    break
                spans.append((pos, pos + len(term)))
                idx = pos + 1

        to_remove = set()
        for ann in doc.annotations:
            for s, e in spans:
                if ann.start_char >= s and ann.end_char <= e:
                    to_remove.add(ann)
                    break
        doc.annotations.difference_update(to_remove)


class CustomOverlapResolver(DocProcessor):
    """Keep highest-priority (then longest) annotation when spans overlap."""

    def process(self, doc, **kwargs):
        ranked = sorted(
            doc.annotations,
            key=lambda a: (-a.priority, -(a.end_char - a.start_char), a.start_char),
        )
        resolved = AnnotationSet()
        for ann in ranked:
            if not any(
                ann.start_char < ex.end_char and ann.end_char > ex.start_char
                for ex in resolved
            ):
                resolved.add(ann)
        doc.annotations = resolved


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_list(filepath):
    """Read a text file with one entry per line (skip comments and blanks)."""
    entries = []
    with open(filepath, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                entries.append(line)
    return entries


# ---------------------------------------------------------------------------
# Pipeline builder
# ---------------------------------------------------------------------------

def build_pipeline(patient_info, data_dir):
    """Construct a DocDeid de-identification pipeline."""
    deid = DocDeid()
    tokenizer = WordBoundaryTokenizer()
    deid.tokenizers["default"] = tokenizer

    # -- load lookup data --
    first_names = load_list(data_dir / "first_names.txt")
    surnames = load_list(data_dir / "surnames.txt")
    interfixes = load_list(data_dir / "interfixes.txt")
    places = load_list(data_dir / "places.txt")
    streets = load_list(data_dir / "streets.txt")
    institutions = load_list(data_dir / "institutions.txt")
    medical_terms = load_list(data_dir / "medical_terms.txt")

    # -- derive multi-word name patterns --
    multi_word_names = set()
    for interfix in interfixes:
        for surname in surnames:
            multi_word_names.add(f"{interfix} {surname}")

    # patient-specific additions
    pat_first = patient_info.get("first_names", [])
    pat_surname = patient_info.get("surname", "")

    if " " in pat_surname:
        multi_word_names.add(pat_surname)
    if "-" in pat_surname:
        for part in pat_surname.split("-"):
            part = part.strip()
            if " " in part:
                multi_word_names.add(part)

    # add surname base parts to single-token list
    all_surnames = list(surnames)
    if pat_surname:
        for part in pat_surname.replace("-", " ").split():
            if part and part[0].isupper():
                all_surnames.append(part)
    all_surnames = list(set(all_surnames))
    all_first = list(set(first_names + pat_first))

    # -- annotators --
    lc = [LowercaseString()]

    # First names
    deid.processors.add_processor(
        "first_names",
        SingleTokenLookupAnnotator(
            lookup_values=all_first, matching_pipeline=lc,
            tag="naam", priority=5,
        ),
    )

    # Surnames (single token)
    deid.processors.add_processor(
        "surnames",
        SingleTokenLookupAnnotator(
            lookup_values=all_surnames, matching_pipeline=lc,
            tag="naam", priority=5,
        ),
    )

    # Multi-word names (interfix + surname)
    deid.processors.add_processor(
        "multi_names",
        MultiTokenLookupAnnotator(
            lookup_values=list(multi_word_names), tokenizer=tokenizer,
            matching_pipeline=lc, tag="naam", priority=7,
            overlapping=True,
        ),
    )

    # Initials (e.g. J.W., M.E.)
    deid.processors.add_processor(
        "initials",
        RegexpAnnotator(
            regexp_pattern=r"(?<!\w)((?:[A-Z]\.){1,4})(?=\s)",
            tag="naam", priority=3, capturing_group=1,
        ),
    )

    # Streets (regex-based for reliable multi-word matching)
    street_pattern = "|".join(
        re.escape(s) for s in sorted(streets, key=len, reverse=True)
    )
    deid.processors.add_processor(
        "streets",
        RegexpAnnotator(
            regexp_pattern=rf"(?:{street_pattern})",
            tag="locatie", priority=6,
        ),
    )

    # Institutions (regex-based for reliable multi-word matching)
    inst_pattern = "|".join(
        re.escape(s) for s in sorted(institutions, key=len, reverse=True)
    )
    deid.processors.add_processor(
        "institutions",
        RegexpAnnotator(
            regexp_pattern=rf"(?:{inst_pattern})",
            tag="instelling", priority=6,
        ),
    )

    # Places (single token)
    deid.processors.add_processor(
        "places",
        SingleTokenLookupAnnotator(
            lookup_values=places, matching_pipeline=lc,
            tag="locatie", priority=4,
        ),
    )

    # BSN (elfproef)
    deid.processors.add_processor(
        "bsn",
        BsnAnnotator(
            bsn_regexp=r"(?<!\d)(\d{9})(?!\d)",
            capture_group=1, tag="bsn", priority=100,
        ),
    )

    # Dates -- numeric DD-MM-YYYY / DD/MM/YYYY
    deid.processors.add_processor(
        "date_numeric",
        RegexpAnnotator(
            regexp_pattern=(
                r"(?<!\d)"
                r"((?:[1-9]|0[1-9]|[12]\d|3[01])"
                r"(?P<dsep>[-/])"
                r"(?:[1-9]|0[1-9]|1[012])"
                r"(?P=dsep)"
                r"(?:(?:19|20)?\d{2}))"
                r"(?!\d)"
            ),
            tag="datum", priority=5, capturing_group=1,
        ),
    )

    # Dates -- Dutch text (e.g. "25 augustus 1972")
    months = (
        "januari|februari|maart|april|mei|juni|juli|"
        "augustus|september|oktober|november|december"
    )
    deid.processors.add_processor(
        "date_text",
        RegexpAnnotator(
            regexp_pattern=(
                rf"(?i)(?<!\d)"
                rf"((?:[1-9]|0[1-9]|[12]\d|3[01])"
                rf"\s+(?:{months})"
                rf"\s+(?:(?:19|20)?\d{{2}}))"
                rf"(?!\d)"
            ),
            tag="datum", priority=5, capturing_group=1,
            pre_match_words=[m for m in months.split("|")],
        ),
    )

    # Phone numbers
    deid.processors.add_processor(
        "phone",
        PhoneNumberAnnotator(
            phone_regexp=(
                r"(?<!\d)"
                r"(?:\+31[\s-]?\d{1,2}[\s-]?\d{7,8}"
                r"|0\d{1,2}[-]?\d{7,8})"
                r"(?!\d)"
            ),
            tag="telefoonnummer", priority=5,
            min_digits=9, max_digits=11,
        ),
    )

    # Email
    deid.processors.add_processor(
        "email",
        RegexpAnnotator(
            regexp_pattern=r"[\w.+-]+@[\w-]+\.\w+",
            tag="email", priority=8,
        ),
    )

    # Postal codes (e.g. 9712 HH)
    deid.processors.add_processor(
        "postal_code",
        RegexpAnnotator(
            regexp_pattern=r"(\d{4}\s?[A-Z]{2})(?!\w)",
            tag="locatie", priority=5, capturing_group=1,
        ),
    )

    # Ages (e.g. "39 jaar", "55 jaar oud")
    deid.processors.add_processor(
        "age",
        RegexpAnnotator(
            regexp_pattern=r"(?<![,.\d])(\d{1,3}\s*jaar(?:\s+oud)?)(?!\w)",
            tag="leeftijd", priority=5, capturing_group=1,
        ),
    )

    # -- post-processing --

    deid.processors.add_processor("medical_filter", MedicalTermFilter(medical_terms))
    deid.processors.add_processor("overlap_resolver", CustomOverlapResolver())
    deid.processors.add_processor("redactor", SimpleRedactor())

    return deid


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_document(input_file, patient_id, output_dir):
    """Process a single clinical document."""
    data_dir = Path("/app/data")

    with open("/app/patients.json", "r", encoding="utf-8") as fh:
        patients = json.load(fh)

    patient_info = patients.get(patient_id, {})

    with open(input_file, "r", encoding="utf-8") as fh:
        text = fh.read()

    pipeline = build_pipeline(patient_info, data_dir)
    doc = pipeline.deidentify(text)

    os.makedirs(output_dir, exist_ok=True)
    basename = Path(input_file).stem

    # write redacted text
    with open(os.path.join(output_dir, f"{basename}.txt"), "w", encoding="utf-8") as fh:
        fh.write(doc.deidentified_text)

    # write annotations JSON
    ann_list = [
        {
            "text": a.text,
            "start_char": a.start_char,
            "end_char": a.end_char,
            "tag": a.tag,
        }
        for a in sorted(doc.annotations, key=lambda a: a.start_char)
    ]
    with open(
        os.path.join(output_dir, f"{basename}.annotations.json"), "w", encoding="utf-8"
    ) as fh:
        json.dump(ann_list, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <input_file> <patient_id> [output_dir]")
        sys.exit(1)
    process_document(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3] if len(sys.argv) > 3 else "/app/output",
    )
