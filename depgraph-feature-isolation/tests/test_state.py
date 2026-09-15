
import os
import sys
sys.path.insert(0, '/app')

import pytest

from isolator.analyzer import classify

PROJECT_DIR = '/app/codebase'
PACKAGE_NAME = 'codebase'
FEATURE_DIR = '/app/test_suites/feature'
BASE_DIR = '/app/test_suites/base'

ALL_EXPECTED_FUNCTIONS = {
    'core.validation.check_type',
    'core.validation.check_positive',
    'core.validation.check_nonempty',
    'core.validation.check_range',
    'core.validation.validate_schema',
    'core.formatting.round_val',
    'core.formatting.pad_string',
    'core.formatting.format_table',
    'transforms.numeric.scale',
    'transforms.numeric.normalize_value',
    'transforms.numeric.safe_divide',
    'transforms.numeric._clamp',
    'transforms.text.clean_text',
    'transforms.text.tokenize',
    'transforms.text.truncate_text',
    'analysis.geometry.distance',
    'analysis.geometry.triangle_area',
    'analysis.geometry.point_in_rect',
    'analysis.geometry.scale_point',
    'analysis.nlp.word_count',
    'analysis.nlp.summarize',
    'analysis.stats.mean_val',
    'analysis.stats.std_dev',
    'analysis.stats.correlate',
    'utils.helpers.compose',
}

EXPECTED_FEATURE_ONLY = {
    'analysis.geometry.distance',
    'analysis.geometry.triangle_area',
    'analysis.geometry.point_in_rect',
    'analysis.geometry.scale_point',
    'analysis.stats.mean_val',
    'analysis.stats.std_dev',
    'analysis.stats.correlate',
    'core.formatting.round_val',
    'core.validation.check_positive',
    'transforms.numeric.normalize_value',
    'transforms.numeric.scale',
}

EXPECTED_BASE_ONLY = {
    'analysis.nlp.word_count',
    'analysis.nlp.summarize',
    'transforms.text.tokenize',
    'transforms.text.clean_text',
    'transforms.text.truncate_text',
    'core.validation.check_nonempty',
}

EXPECTED_SHARED = {
    'core.validation.check_type',
}

EXPECTED_UNUSED = {
    'core.validation.check_range',
    'core.validation.validate_schema',
    'core.formatting.pad_string',
    'core.formatting.format_table',
    'transforms.numeric.safe_divide',
    'transforms.numeric._clamp',
    'utils.helpers.compose',
}


class TestFunctionDiscovery:
    """Verify that all function definitions are correctly discovered."""

    def test_discovers_all_functions(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert set(result.keys()) == ALL_EXPECTED_FUNCTIONS

    def test_function_count(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert len(result) == 25

    def test_valid_labels(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        valid = {'feature_only', 'base_only', 'shared', 'unused'}
        for func, label in result.items():
            assert label in valid, f"{func} has invalid label: {label}"


class TestClassification:
    """Verify the exact function classification output."""

    def test_feature_only_set(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        actual = {k for k, v in result.items() if v == 'feature_only'}
        assert actual == EXPECTED_FEATURE_ONLY

    def test_base_only_set(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        actual = {k for k, v in result.items() if v == 'base_only'}
        assert actual == EXPECTED_BASE_ONLY

    def test_shared_set(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        actual = {k for k, v in result.items() if v == 'shared'}
        assert actual == EXPECTED_SHARED

    def test_unused_set(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        actual = {k for k, v in result.items() if v == 'unused'}
        assert actual == EXPECTED_UNUSED

    def test_classification_counts(self):
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        counts = {}
        for v in result.values():
            counts[v] = counts.get(v, 0) + 1
        assert counts['feature_only'] == 11
        assert counts['base_only'] == 6
        assert counts['shared'] == 1
        assert counts['unused'] == 7


class TestImportPatterns:
    """Verify that specific import patterns are correctly resolved."""

    def test_init_reexport_resolution(self):
        """Functions imported via __init__.py re-exports must be correctly traced."""
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert result['core.validation.check_positive'] == 'feature_only'
        assert result['core.formatting.round_val'] == 'feature_only'

    def test_star_import_with_all(self):
        """Star import respecting __all__ must resolve correctly."""
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert result['transforms.numeric.scale'] == 'feature_only'
        assert result['transforms.numeric.normalize_value'] == 'feature_only'
        assert result['transforms.numeric._clamp'] == 'unused'

    def test_aliased_function_imports(self):
        """Aliased imports (import X as Y) must resolve to original function."""
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert result['transforms.text.clean_text'] == 'base_only'
        assert result['transforms.text.truncate_text'] == 'base_only'

    def test_module_alias_attribute_access(self):
        """Module aliases (import mod as m; m.func()) must resolve correctly."""
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert result['core.validation.check_type'] == 'shared'
        assert result['core.validation.check_nonempty'] == 'base_only'

    def test_relative_import_resolution(self):
        """Relative imports (from ..mod import func) must resolve correctly."""
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert result['analysis.stats.mean_val'] == 'feature_only'
        assert result['analysis.stats.std_dev'] == 'feature_only'
        assert result['analysis.stats.correlate'] == 'feature_only'

    def test_intra_module_calls(self):
        """Calls between functions in the same module must be tracked."""
        result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
        assert result['analysis.stats.std_dev'] == 'feature_only'
        assert result['transforms.text.tokenize'] == 'base_only'


class TestDynamic:
    """Anti-cheat: classification must update when project/tests change at runtime."""

    def test_adding_base_test_promotes_to_shared(self):
        """Adding a base test importing a feature function reclassifies it as shared."""
        test_path = os.path.join(BASE_DIR, 'test_distance_cross.py')
        test_code = (
            'from codebase.analysis.geometry import distance\n'
            '\n'
            'def test_distance_cross():\n'
            '    assert distance((0, 0), (3, 4)) == 5.0\n'
        )
        try:
            with open(test_path, 'w') as f:
                f.write(test_code)
            result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
            assert result['analysis.geometry.distance'] == 'shared'
            assert result['core.formatting.round_val'] == 'shared'
            assert result['analysis.geometry.triangle_area'] == 'feature_only'
            assert result['analysis.nlp.word_count'] == 'base_only'
        finally:
            if os.path.exists(test_path):
                os.remove(test_path)

    def test_new_function_discovered_as_unused(self):
        """Adding a new source file must discover its functions as unused."""
        extra_path = os.path.join(PROJECT_DIR, 'analysis', 'extra.py')
        try:
            with open(extra_path, 'w') as f:
                f.write('def auxiliary_func(x):\n    return x * 2\n')
            result = classify(PROJECT_DIR, PACKAGE_NAME, FEATURE_DIR, BASE_DIR)
            assert 'analysis.extra.auxiliary_func' in result
            assert result['analysis.extra.auxiliary_func'] == 'unused'
            assert len(result) == 26
        finally:
            if os.path.exists(extra_path):
                os.remove(extra_path)
