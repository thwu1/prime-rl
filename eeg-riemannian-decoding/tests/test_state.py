
import pytest
import numpy as np
import sys
import os
import json

sys.path.insert(0, '/app')


class TestPipelineResults:
    """Verify the cross-subject EEG decoding pipeline output."""

    def test_results_file_exists(self):
        assert os.path.exists('/app/results.json'), \
            "Pipeline must generate /app/results.json"

    def test_results_format(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        for key in ['accuracies', 'mean_accuracy', 'n_subjects', 'method']:
            assert key in results, "results.json missing key: {}".format(key)

        assert isinstance(results['accuracies'], list)
        assert isinstance(results['mean_accuracy'], (int, float))
        assert isinstance(results['n_subjects'], int)
        assert isinstance(results['method'], str)

    def test_accuracies_count_matches_subjects(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        meta = np.load('/app/data/metadata.npz')
        n_subjects = int(meta['n_subjects'][0])

        assert len(results['accuracies']) == n_subjects, \
            "Expected {} accuracies, got {}".format(
                n_subjects, len(results['accuracies']))

    def test_accuracy_values_valid(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        for i, acc in enumerate(results['accuracies']):
            assert 0 <= acc <= 1, \
                "Subject {} accuracy out of range: {}".format(i, acc)

    def test_mean_accuracy_consistent(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        expected = np.mean(results['accuracies'])
        assert abs(results['mean_accuracy'] - expected) < 1e-6, \
            "mean_accuracy ({}) != mean of accuracies ({})".format(
                results['mean_accuracy'], expected)

    def test_mean_accuracy_above_threshold(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        assert results['mean_accuracy'] > 0.58, \
            "Mean accuracy {:.4f} below required threshold 0.58".format(
                results['mean_accuracy'])

    def test_per_subject_above_minimum(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        for i, acc in enumerate(results['accuracies']):
            assert acc > 0.42, \
                "Subject {} accuracy {:.4f} below minimum 0.42".format(i, acc)

    def test_n_subjects_matches_data(self):
        with open('/app/results.json') as f:
            results = json.load(f)

        meta = np.load('/app/data/metadata.npz')
        n_subjects = int(meta['n_subjects'][0])

        assert results['n_subjects'] == n_subjects, \
            "Reported n_subjects ({}) does not match dataset ({})".format(
                results['n_subjects'], n_subjects)

    def test_pipeline_module_exposes_decoder(self):
        import pipeline

        assert hasattr(pipeline, 'cross_subject_decode'), \
            "pipeline.py must expose cross_subject_decode function"
        assert callable(pipeline.cross_subject_decode), \
            "pipeline.cross_subject_decode must be callable"

    def test_loso_cv_structure(self):
        """Verify LOSO-CV produces distinct per-subject results."""
        with open('/app/results.json') as f:
            results = json.load(f)

        n = len(results['accuracies'])
        unique_accs = len(set(round(a, 6) for a in results['accuracies']))
        assert unique_accs >= 2, \
            "All accuracies are identical ({} unique out of {}), " \
            "suggests cross-validation is not actually per-subject".format(
                unique_accs, n)

    def test_pipeline_not_trivial(self):
        """Pipeline must contain substantial implementation."""
        with open('/app/pipeline.py') as f:
            code = f.read()

        assert len(code) > 500, \
            "pipeline.py is too short to contain a real implementation"
        assert 'numpy' in code or 'np.' in code, \
            "pipeline.py should perform numerical computation"

    def test_pipeline_reads_data(self):
        """cross_subject_decode must actually read from data_dir."""
        import pipeline

        raised = False
        try:
            pipeline.cross_subject_decode('/nonexistent_data_dir_abc123')
        except Exception:
            raised = True

        assert raised, \
            "cross_subject_decode should fail with nonexistent data_dir, " \
            "suggesting results may be hardcoded"
