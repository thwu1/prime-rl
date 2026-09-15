
"""
Tests for multi-relational ontology alignment task.
Verifies the output alignment against a gold standard using
per-relation-type precision/recall/F1 and weighted macro-F1.
"""

import os
import xml.etree.ElementTree as ET
from collections import defaultdict

ALIGNMENT_PATH = "/app/output/alignment.rdf"

GPC = "http://example.org/gpc#"
RPT = "http://example.org/rpt#"

# Gold standard: list of (source_local, target_local, relation)
GOLD_STANDARD = [
    # === EQUIVALENCE (=) : 19 pairs ===
    ("FoodProduct", "Edible", "="),
    ("Fish", "FishItem", "="),
    ("Shellfish", "ShellfishItem", "="),
    ("Fruit", "FruitItem", "="),
    ("Vegetable", "VegetableItem", "="),
    ("Bread", "BreadLoaf", "="),
    ("Cake", "CakeItem", "="),
    ("Pastry", "PastryItem", "="),
    ("Rice", "RiceItem", "="),
    ("Pasta", "PastaItem", "="),
    ("Cereal", "CerealItem", "="),
    ("AlcoholicDrink", "BeerWineLiquor", "="),
    ("PaperTowel", "KitchenTowel", "="),
    ("Tissue", "FacialTissue", "="),
    ("BakeryProduct", "BakedItem", "="),
    ("HairCareProduct", "HairProduct", "="),
    ("SkinCareProduct", "SkinProduct", "="),
    ("OralCareProduct", "DentalProduct", "="),
    ("PersonalCareProduct", "BodyCareProduct", "="),
    # === SUPERCLASS_OF (>) : 11 pairs ===
    ("DairyProduct", "LiquidDairy", ">"),
    ("DairyProduct", "SolidDairy", ">"),
    ("DairyProduct", "CulturedDairy", ">"),
    ("MeatProduct", "BeefProduct", ">"),
    ("MeatProduct", "PorkProduct", ">"),
    ("MeatProduct", "ChickenProduct", ">"),
    ("Beverage", "CoffeeTeaDrink", ">"),
    ("Beverage", "JuiceSodaDrink", ">"),
    ("Beverage", "WaterDrink", ">"),
    ("CleaningAgent", "FabricCleaner", ">"),
    ("CleaningAgent", "SurfaceCleaner", ">"),
    # === SUBCLASS_OF (<) : 9 pairs ===
    ("Milk", "LiquidDairy", "<"),
    ("Cheese", "SolidDairy", "<"),
    ("Butter", "SolidDairy", "<"),
    ("Yogurt", "CulturedDairy", "<"),
    ("RedMeat", "ProteinItem", "<"),
    ("Poultry", "ProteinItem", "<"),
    ("LaundryProduct", "CleaningProduct", "<"),
    ("DishwashingProduct", "CleaningProduct", "<"),
    ("Herb", "HerbSpice", "<"),
    # === OVERLAP (~) : 5 pairs ===
    ("HotDrink", "CoffeeTeaDrink", "~"),
    ("ColdDrink", "JuiceSodaDrink", "~"),
    ("ProcessedMeat", "DeliMeat", "~"),
    ("GrainProduct", "StapleItem", "~"),
    ("FreshProduce", "ProduceItem", "~"),
    # === DISJOINT (%) : 8 pairs ===
    ("DairyProduct", "CleaningProduct", "%"),
    ("MeatProduct", "BakedItem", "%"),
    ("BakeryProduct", "ProteinItem", "%"),
    ("Beverage", "PaperProduct", "%"),
    ("FreshProduce", "BodyCareProduct", "%"),
    ("GrainProduct", "PaperProduct", "%"),
    ("CleaningAgent", "DairyItem", "%"),
    ("PaperGoods", "Edible", "%"),
]

VALID_RELATIONS = {"=", ">", "<", "~", "%"}

# Build gold set as (full_src_uri, full_tgt_uri, relation)
GOLD_SET = {(GPC + s, RPT + t, r) for s, t, r in GOLD_STANDARD}


def parse_alignment(path):
    """Parse OAEI alignment XML and return list of (entity1, entity2, relation, measure)."""
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle namespace variations
    ns_align = "http://knowledgeweb.semanticweb.org/heterogeneity/alignment"
    ns_rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"

    cells = []

    # Try multiple ways to find Cell elements
    for cell in root.iter():
        tag = cell.tag
        # Strip namespace if present
        local_tag = tag.split("}")[-1] if "}" in tag else tag
        if local_tag != "Cell":
            continue

        e1 = None
        e2 = None
        rel = None
        measure = None

        for child in cell:
            child_tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if child_tag == "entity1":
                e1 = child.get(f"{{{ns_rdf}}}resource") or child.get("rdf:resource")
            elif child_tag == "entity2":
                e2 = child.get(f"{{{ns_rdf}}}resource") or child.get("rdf:resource")
            elif child_tag == "relation":
                rel = (child.text or "").strip()
            elif child_tag == "measure":
                try:
                    measure = float(child.text or "0")
                except ValueError:
                    measure = 0.0

        if e1 and e2 and rel:
            cells.append((e1, e2, rel, measure or 0.0))

    return cells


def compute_metrics(predicted, gold, relation_type):
    """Compute precision, recall, F1 for a specific relation type."""
    pred_set = {(e1, e2) for e1, e2, r in predicted if r == relation_type}
    gold_set = {(e1, e2) for e1, e2, r in gold if r == relation_type}

    if not gold_set:
        return 1.0, 1.0, 1.0  # no gold entries for this type

    tp = len(pred_set & gold_set)
    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(gold_set) if gold_set else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return precision, recall, f1


class TestAlignmentExists:
    def test_output_file_exists(self):
        assert os.path.isfile(ALIGNMENT_PATH), (
            f"Output alignment file not found at {ALIGNMENT_PATH}"
        )

    def test_output_is_valid_xml(self):
        assert os.path.isfile(ALIGNMENT_PATH), "Alignment file missing"
        try:
            ET.parse(ALIGNMENT_PATH)
        except ET.ParseError as e:
            raise AssertionError(f"Output is not valid XML: {e}")


class TestAlignmentFormat:
    def test_contains_alignment_cells(self):
        cells = parse_alignment(ALIGNMENT_PATH)
        assert len(cells) > 0, "No alignment cells found in output"

    def test_cells_have_valid_relations(self):
        cells = parse_alignment(ALIGNMENT_PATH)
        for e1, e2, rel, _ in cells:
            assert rel in VALID_RELATIONS, (
                f"Invalid relation '{rel}' for {e1} -> {e2}. "
                f"Must be one of {VALID_RELATIONS}"
            )

    def test_cells_use_correct_namespaces(self):
        cells = parse_alignment(ALIGNMENT_PATH)
        gpc_found = False
        rpt_found = False
        for e1, e2, _, _ in cells:
            if GPC in e1:
                gpc_found = True
            if RPT in e2:
                rpt_found = True
        assert gpc_found, f"No entity1 URIs use the source namespace {GPC}"
        assert rpt_found, f"No entity2 URIs use the target namespace {RPT}"

    def test_minimum_alignment_count(self):
        cells = parse_alignment(ALIGNMENT_PATH)
        assert len(cells) >= 20, (
            f"Too few alignments: {len(cells)}. Expected at least 20."
        )

    def test_has_multiple_relation_types(self):
        cells = parse_alignment(ALIGNMENT_PATH)
        relation_types = {rel for _, _, rel, _ in cells}
        assert len(relation_types) >= 4, (
            f"Only {len(relation_types)} relation types found: {relation_types}. "
            f"Expected at least 4 of {VALID_RELATIONS}."
        )


class TestAlignmentQuality:
    def _get_predicted(self):
        cells = parse_alignment(ALIGNMENT_PATH)
        return [(e1, e2, rel) for e1, e2, rel, _ in cells]

    def _get_gold(self):
        return [(GPC + s, RPT + t, r) for s, t, r in GOLD_STANDARD]

    def test_equivalence_f1(self):
        predicted = self._get_predicted()
        gold = self._get_gold()
        _, _, f1 = compute_metrics(predicted, gold, "=")
        assert f1 >= 0.40, (
            f"Equivalence F1 = {f1:.3f}, expected >= 0.40"
        )

    def test_superclass_f1(self):
        predicted = self._get_predicted()
        gold = self._get_gold()
        _, _, f1 = compute_metrics(predicted, gold, ">")
        assert f1 >= 0.30, (
            f"Superclass_of F1 = {f1:.3f}, expected >= 0.30"
        )

    def test_subclass_f1(self):
        predicted = self._get_predicted()
        gold = self._get_gold()
        _, _, f1 = compute_metrics(predicted, gold, "<")
        assert f1 >= 0.25, (
            f"Subclass_of F1 = {f1:.3f}, expected >= 0.25"
        )

    def test_weighted_macro_f1(self):
        predicted = self._get_predicted()
        gold = self._get_gold()

        # Count gold entries per relation type
        type_counts = defaultdict(int)
        for _, _, r in gold:
            type_counts[r] += 1

        total_gold = len(gold)
        weighted_f1 = 0.0

        for rel_type in VALID_RELATIONS:
            _, _, f1 = compute_metrics(predicted, gold, rel_type)
            weight = type_counts.get(rel_type, 0) / total_gold
            weighted_f1 += weight * f1

        assert weighted_f1 >= 0.55, (
            f"Weighted macro-F1 = {weighted_f1:.3f}, expected >= 0.55. "
            f"Per-type F1: { {r: compute_metrics(predicted, gold, r)[2] for r in VALID_RELATIONS} }"
        )

    def test_overall_precision_minimum(self):
        predicted = self._get_predicted()
        gold_tuples = {(GPC + s, RPT + t, r) for s, t, r in GOLD_STANDARD}

        correct = sum(1 for p in predicted if tuple(p) in gold_tuples)
        precision = correct / len(predicted) if predicted else 0.0

        assert precision >= 0.30, (
            f"Overall precision = {precision:.3f}, expected >= 0.30. "
            f"{correct} correct out of {len(predicted)} predicted."
        )
