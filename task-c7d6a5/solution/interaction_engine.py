#!/usr/bin/env python3

"""
Drug interaction detection engine.

Implements a three-tier interaction checking cascade:
  1. Direct drug-drug interaction lookup (RxNorm code pairs)
  2. Pharmacological class-level interaction (drug class membership matching)
  3. Allergy cross-reactivity (allergen group membership)
"""

import json
import os
import uuid

RXNORM_SYSTEM = "http://www.nlm.nih.gov/research/umls/rxnorm"


class InteractionEngine:
    def __init__(self, data_dir):
        with open(os.path.join(data_dir, "drug_interactions.json")) as f:
            data = json.load(f)
            self.interactions = data["interactions"]

        with open(os.path.join(data_dir, "drug_classes.json")) as f:
            data = json.load(f)
            self.drug_to_classes = data["drug_to_classes"]
            self.class_interactions = data["class_interactions"]

        with open(os.path.join(data_dir, "allergy_cross_reactivity.json")) as f:
            data = json.load(f)
            self.cross_reactivity_groups = data["cross_reactivity_groups"]

        # Build bidirectional lookup keyed by sorted (code_a, code_b)
        self.direct_lookup = {}
        for interaction in self.interactions:
            code_a = interaction["drug_a"]["code"]
            code_b = interaction["drug_b"]["code"]
            key = tuple(sorted([code_a, code_b]))
            self.direct_lookup[key] = interaction

    @staticmethod
    def _get_rxnorm_code(medication_request):
        """Extract (code, display) from a MedicationRequest's medicationCodeableConcept."""
        med_cc = medication_request.get("medicationCodeableConcept", {})
        for coding in med_cc.get("coding", []):
            if coding.get("system") == RXNORM_SYSTEM:
                return coding.get("code"), coding.get("display", "Unknown")
        return None, None

    @staticmethod
    def _get_allergy_codes(allergy):
        """Extract list of (code, display) from an AllergyIntolerance's code."""
        results = []
        code_cc = allergy.get("code", {})
        for coding in code_cc.get("coding", []):
            if coding.get("system") == RXNORM_SYSTEM:
                results.append((coding.get("code"), coding.get("display", "Unknown")))
        return results

    def _check_direct_interaction(self, code_a, code_b):
        """Look up a direct drug-drug interaction by sorted code pair."""
        key = tuple(sorted([code_a, code_b]))
        return self.direct_lookup.get(key)

    def _check_class_interaction(self, code_a, code_b):
        """Check for class-level interaction between two drugs."""
        classes_a = set(self.drug_to_classes.get(code_a, []))
        classes_b = set(self.drug_to_classes.get(code_b, []))

        if not classes_a or not classes_b:
            return None

        for ci in self.class_interactions:
            ca = ci["class_a"]
            cb = ci["class_b"]
            if (ca in classes_a and cb in classes_b) or (cb in classes_a and ca in classes_b):
                return ci
        return None

    def _check_allergy_cross_reactivity(self, drug_code, allergies):
        """Check if a drug cross-reacts with any of the patient's documented allergies."""
        for allergy in allergies:
            allergy_codes = self._get_allergy_codes(allergy)
            for allergen_code, allergen_display in allergy_codes:
                for group in self.cross_reactivity_groups:
                    allergen_in_group = any(
                        ac["code"] == allergen_code for ac in group["allergen_codes"]
                    )
                    drug_cross_reactive = drug_code in group["cross_reactive_drug_codes"]

                    if allergen_in_group and drug_cross_reactive:
                        return group, allergen_display
        return None, None

    @staticmethod
    def _make_card(summary, detail, indicator, source_label="Medication Safety CDS Service"):
        """Create a CDS Hooks card conforming to the specification."""
        return {
            "uuid": str(uuid.uuid4()),
            "summary": summary,
            "detail": detail,
            "indicator": indicator,
            "source": {"label": source_label},
        }

    def check_all(self, draft_orders, current_meds, allergies):
        """
        Check all draft medication orders against current medications and allergies.

        Returns a list of CDS cards for detected interactions.
        """
        cards = []
        seen_interactions = set()

        for draft in draft_orders:
            draft_code, draft_display = self._get_rxnorm_code(draft)
            if not draft_code:
                continue

            # ── Drug-drug interaction checks ──
            for med in current_meds:
                med_code, med_display = self._get_rxnorm_code(med)
                if not med_code:
                    continue

                interaction_key = tuple(sorted([draft_code, med_code]))
                if interaction_key in seen_interactions:
                    continue

                # Tier 1: Direct interaction lookup
                interaction = self._check_direct_interaction(draft_code, med_code)
                if interaction:
                    seen_interactions.add(interaction_key)
                    cards.append(
                        self._make_card(
                            summary=f"Drug Interaction: {draft_display} + {med_display}",
                            detail=interaction["description"],
                            indicator=interaction["severity"],
                        )
                    )
                    continue

                # Tier 2: Class-level interaction
                class_interaction = self._check_class_interaction(draft_code, med_code)
                if class_interaction:
                    seen_interactions.add(interaction_key)
                    cards.append(
                        self._make_card(
                            summary=f"Drug Class Interaction: {draft_display} + {med_display}",
                            detail=class_interaction["description"],
                            indicator=class_interaction["severity"],
                        )
                    )

            # ── Allergy cross-reactivity check ──
            group, allergen_display = self._check_allergy_cross_reactivity(
                draft_code, allergies
            )
            if group:
                cards.append(
                    self._make_card(
                        summary=(
                            f"Allergy Cross-Reactivity: {draft_display} "
                            f"(patient allergic to {allergen_display})"
                        ),
                        detail=group["description"],
                        indicator=group["severity"],
                    )
                )

        return cards
