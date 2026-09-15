
import json
import os
import pytest


def load_results():
    with open('/app/corrected_report.json', 'r') as f:
        return json.load(f)


def load_error_analysis():
    with open('/app/error_analysis.json', 'r') as f:
        return json.load(f)


def test_results_file_exists():
    assert os.path.isfile('/app/corrected_report.json'), \
        "/app/corrected_report.json not found"


def test_error_analysis_file_exists():
    assert os.path.isfile('/app/error_analysis.json'), \
        "/app/error_analysis.json not found"


def test_results_valid_json():
    results = load_results()
    assert isinstance(results, dict), \
        "corrected_report.json must contain a JSON object"


def test_all_keys_present():
    results = load_results()
    required = [
        'phantom_duplicate_groups',
        'inventory_text_quantities',
        'product_text_prices',
        'orphaned_product_categories',
        'orphaned_transactions',
        'max_category_depth',
        'json_price_discrepancies',
        'stat1_anomalies',
        'total_inventory_value',
        'inventory_value_by_root_category',
    ]
    for key in required:
        assert key in results, f"Missing required key: {key}"


def test_phantom_duplicate_groups():
    results = load_results()
    assert results['phantom_duplicate_groups'] == 5


def test_inventory_text_quantities():
    results = load_results()
    assert results['inventory_text_quantities'] == 7


def test_product_text_prices():
    results = load_results()
    assert results['product_text_prices'] == 3


def test_orphaned_product_categories():
    results = load_results()
    assert results['orphaned_product_categories'] == 2


def test_orphaned_transactions():
    results = load_results()
    assert results['orphaned_transactions'] == 8


def test_max_category_depth():
    results = load_results()
    assert results['max_category_depth'] == 5


def test_json_price_discrepancies():
    results = load_results()
    assert results['json_price_discrepancies'] == 5


def test_stat1_anomalies():
    results = load_results()
    assert results['stat1_anomalies'] == 3


def test_total_inventory_value():
    results = load_results()
    assert results['total_inventory_value'] == pytest.approx(960467.15, abs=0.10)


def test_inventory_value_by_root_category_structure():
    results = load_results()
    root_cats = results['inventory_value_by_root_category']
    assert isinstance(root_cats, dict), \
        "inventory_value_by_root_category must be a dict"
    assert len(root_cats) == 3, \
        f"Expected 3 root categories, got {len(root_cats)}"
    assert set(root_cats.keys()) == {'Electronics', 'Clothing', 'Accessories'}, \
        f"Unexpected root category keys: {set(root_cats.keys())}"


def test_inventory_value_electronics():
    results = load_results()
    root_cats = results['inventory_value_by_root_category']
    assert root_cats['Electronics'] == pytest.approx(718780.00, abs=0.10)


def test_inventory_value_clothing():
    results = load_results()
    root_cats = results['inventory_value_by_root_category']
    assert root_cats['Clothing'] == pytest.approx(47251.15, abs=0.10)


def test_inventory_value_accessories():
    results = load_results()
    root_cats = results['inventory_value_by_root_category']
    assert root_cats['Accessories'] == pytest.approx(194436.00, abs=0.10)


def test_error_analysis_structure():
    analysis = load_error_analysis()
    assert isinstance(analysis, dict), \
        "error_analysis.json must contain a JSON object"
    assert 'correct_keys' in analysis, \
        "error_analysis.json must have 'correct_keys' key"
    assert isinstance(analysis['correct_keys'], list), \
        "correct_keys must be a list"


def test_error_analysis_correct_keys():
    analysis = load_error_analysis()
    expected = ['json_price_discrepancies', 'orphaned_product_categories', 'orphaned_transactions']
    assert analysis['correct_keys'] == expected, \
        f"Expected correct_keys {expected}, got {analysis['correct_keys']}"


def test_error_analysis_count():
    analysis = load_error_analysis()
    assert len(analysis['correct_keys']) == 3, \
        f"Expected exactly 3 correct keys, got {len(analysis['correct_keys'])}"
