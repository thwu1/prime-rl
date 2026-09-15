#!/usr/bin/env python3
"""PII detection and format-preserving anonymization pipeline.

Uses Microsoft Presidio's AnalyzerEngine with custom PatternRecognizer
subclasses to detect PII, then applies format-preserving anonymization
where each replacement value passes the same checksum algorithm as the
original.

Usage: python3 pipeline.py [--seed SEED]
"""

import json
import os
import sys

sys.path.insert(0, "/app")

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider
from presidio_analyzer.recognizer_registry import RecognizerRegistry

from custom_recognizers import (
    CustomCreditCardRecognizer,
    CustomDeTaxIdRecognizer,
    CustomDeHealthInsuranceRecognizer,
    CustomIbanRecognizer,
    CustomItFiscalCodeRecognizer,
)

CORPUS_PATH = "/app/corpus/clinical_records.txt"
OUTPUT_DIR = "/app/output"
DETECTIONS_PATH = os.path.join(OUTPUT_DIR, "detections.json")
ANONYMIZED_PATH = os.path.join(OUTPUT_DIR, "anonymized.txt")

ENTITY_TYPES = [
    "CREDIT_CARD",
    "DE_TAX_ID",
    "DE_HEALTH_INSURANCE",
    "IBAN_CODE",
    "IT_FISCAL_CODE",
]


def create_engine():
    """Create the Presidio AnalyzerEngine with custom recognizers."""
    provider = NlpEngineProvider(conf_file="/app/config/nlp_config.yaml")
    nlp_engine = provider.create_engine()

    registry = RecognizerRegistry(supported_languages=["en"])
    registry.add_recognizer(CustomCreditCardRecognizer())
    registry.add_recognizer(CustomDeTaxIdRecognizer())
    registry.add_recognizer(CustomDeHealthInsuranceRecognizer())
    registry.add_recognizer(CustomIbanRecognizer())
    registry.add_recognizer(CustomItFiscalCodeRecognizer())

    analyzer = AnalyzerEngine(
        registry=registry,
        nlp_engine=nlp_engine,
        supported_languages=["en"],
        default_score_threshold=0.01,
    )
    return analyzer


def resolve_overlaps(results):
    """Remove overlapping detections, keeping the highest confidence score."""
    sorted_results = sorted(results, key=lambda r: r.score, reverse=True)
    kept = []
    for result in sorted_results:
        overlap = False
        for k in kept:
            if result.start < k.end and result.end > k.start:
                overlap = True
                break
        if not overlap:
            kept.append(result)
    return sorted(kept, key=lambda r: (r.entity_type, r.start))


def anonymize(text, detection_records, seed=42):
    """Apply format-preserving anonymization to detected PII values.

    Each replacement value must:
    - Pass the same checksum/validation algorithm as the original
    - Preserve the format (same length, same structural pattern)
    - Be different from the original
    - Be deterministic (same seed produces same output)

    Args:
        text: Original corpus text
        detection_records: List of dicts with entity_type, start, end, score, original_value
        seed: Random seed for deterministic output

    Returns:
        Tuple of (anonymized_text, updated_detection_records_with_anonymized_values)

    TODO: Implement format-preserving anonymization operators for:
    - CREDIT_CARD: generate replacement digits, recompute Luhn check digit
    - IBAN_CODE: preserve country code, randomize BBAN, recompute Mod-97 check digits
    - DE_TAX_ID: generate 10 random digits, compute ISO 7064 Mod 11,10 check digit
    - IT_FISCAL_CODE: generate valid structural components, compute check character
    - DE_HEALTH_INSURANCE: generate letter + 8 digits, compute GKV check digit
    """
    raise NotImplementedError(
        "Format-preserving anonymization not yet implemented. "
        "Implement operators for each entity type that generate "
        "replacement values passing the same checksum algorithms."
    )


def main():
    seed = 42
    if "--seed" in sys.argv:
        idx = sys.argv.index("--seed")
        seed = int(sys.argv[idx + 1])

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        text = f.read()

    # Detection phase
    analyzer = create_engine()
    results = analyzer.analyze(
        text=text,
        language="en",
        entities=ENTITY_TYPES,
    )
    results = resolve_overlaps(results)

    # Build detection records
    detection_records = []
    for r in results:
        raw_value = text[r.start : r.end]
        clean_value = raw_value.replace("-", "").replace(" ", "")
        detection_records.append(
            {
                "entity_type": r.entity_type,
                "start": r.start,
                "end": r.end,
                "score": round(r.score, 2),
                "original_value": clean_value,
            }
        )

    detection_records.sort(key=lambda d: (d["entity_type"], d["start"]))

    # Anonymization phase
    anonymized_text, detection_records = anonymize(text, detection_records, seed)

    # Write outputs
    with open(DETECTIONS_PATH, "w") as f:
        json.dump(detection_records, f, indent=2)

    with open(ANONYMIZED_PATH, "w") as f:
        f.write(anonymized_text)

    print(f"Pipeline complete. {len(detection_records)} entities detected and anonymized.")


if __name__ == "__main__":
    main()
