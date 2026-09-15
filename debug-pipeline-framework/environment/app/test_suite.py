
"""
Test suite for the PipeWeave data-pipeline framework.

Covers configuration, pipeline execution, record transforms,
ANSI-aware formatting, and schema validation.
"""
import pytest
import sys

sys.path.insert(0, '/app')

from pipeweave.config import PipelineConfig, ConfigError
from pipeweave.engine import PipelineEngine, StageResult
from pipeweave.transforms import (
    merge_records, filter_records, map_fields,
    sort_records, group_by, add_computed_field, deduplicate,
)
from pipeweave.formatter import (
    TableFormatter, colorize, strip_ansi, visible_width, pad_to_width,
)
from pipeweave.schema import SchemaValidator, ValidationError


# ======================================================================
# 1. Configuration - basics (should pass on buggy code)
# ======================================================================

class TestConfigBasics:

    def test_get_and_set(self):
        cfg = PipelineConfig()
        cfg.set('database.host', 'localhost')
        cfg.set('database.port', 5432)
        assert cfg.get('database.host') == 'localhost'
        assert cfg.get('database.port') == 5432

    def test_merge_configs(self):
        cfg1 = PipelineConfig({'a': 1, 'b': {'c': 2}})
        cfg2 = PipelineConfig({'b': {'d': 3}})
        cfg1.merge(cfg2)
        assert cfg1.get('b.c') == 2
        assert cfg1.get('b.d') == 3

    def test_validate_required(self):
        cfg = PipelineConfig({'host': 'localhost'})
        cfg.validate_required(['host'])
        with pytest.raises(ConfigError):
            cfg.validate_required(['host', 'port'])

    def test_flatten(self):
        cfg = PipelineConfig({'a': {'b': 1, 'c': 2}, 'd': 3})
        flat = cfg.flatten()
        assert flat['a.b'] == 1
        assert flat['a.c'] == 2
        assert flat['d'] == 3


# ======================================================================
# 2. Configuration - interpolation (some fail due to regex bug)
# ======================================================================

class TestConfigInterpolation:

    def test_simple_interpolation(self):
        cfg = PipelineConfig({
            'greeting': 'hello',
            'message': '${greeting} world',
        })
        assert cfg.resolve()['message'] == 'hello world'

    def test_dotted_path_interpolation(self):
        cfg = PipelineConfig({
            'database': {'host': 'localhost', 'port': 5432},
            'conn': 'postgresql://${database.host}:${database.port}/mydb',
        })
        assert cfg.resolve()['conn'] == 'postgresql://localhost:5432/mydb'

    def test_identifier_with_digits(self):
        cfg = PipelineConfig({
            'server2': 'backup.example.com',
            'url': 'https://${server2}/api',
        })
        assert cfg.resolve()['url'] == 'https://backup.example.com/api'

    def test_nested_dotted_interpolation(self):
        cfg = PipelineConfig({
            'app': {'name': 'myapp', 'version': '2.0'},
            'deploy': {'tag': '${app.name}-v${app.version}'},
        })
        assert cfg.resolve()['deploy']['tag'] == 'myapp-v2.0'


# ======================================================================
# 3. Pipeline engine - pre-hooks (should pass)
# ======================================================================

class TestPreHooks:

    def test_pre_hooks_fifo_order(self):
        order = []
        def hook_a(r, s): order.append('A'); return r
        def hook_b(r, s): order.append('B'); return r

        engine = PipelineEngine()
        engine.add_pre_hook(hook_a)
        engine.add_pre_hook(hook_b)
        engine.add_stage('noop', lambda d: d)
        engine.execute([1, 2, 3])
        assert order == ['A', 'B']

    def test_stage_execution(self):
        engine = PipelineEngine()
        engine.add_stage('double', lambda d: [x * 2 for x in d])
        result = engine.execute([1, 2, 3])
        assert result.data == [2, 4, 6]

    def test_multi_stage(self):
        engine = PipelineEngine()
        engine.add_stage('add1', lambda d: [x + 1 for x in d])
        engine.add_stage('mul2', lambda d: [x * 2 for x in d])
        result = engine.execute([1, 2, 3])
        assert result.data == [4, 6, 8]


# ======================================================================
# 4. Pipeline engine - post-hooks (fail due to ordering bug)
# ======================================================================

class TestPostHooks:

    def test_post_hooks_lifo_order(self):
        order = []
        def hook_a(r, s): order.append('A'); return r
        def hook_b(r, s): order.append('B'); return r
        def hook_c(r, s): order.append('C'); return r

        engine = PipelineEngine()
        engine.add_post_hook(hook_a)
        engine.add_post_hook(hook_b)
        engine.add_post_hook(hook_c)
        engine.add_stage('noop', lambda d: d)
        engine.execute([1, 2, 3])
        assert order == ['C', 'B', 'A'], (
            f"Post-hooks ran {order}, expected LIFO ['C', 'B', 'A']"
        )

    def test_post_hooks_transform_data_lifo(self):
        def multiply_by_2(result, stage):
            result.data = [x * 2 for x in result.data]
            return result

        def add_10(result, stage):
            result.data = [x + 10 for x in result.data]
            return result

        engine = PipelineEngine()
        engine.add_post_hook(multiply_by_2)
        engine.add_post_hook(add_10)
        engine.add_stage('noop', lambda d: d)
        result = engine.execute([1, 2, 3])
        # LIFO: add_10 first -> [11,12,13], then multiply -> [22,24,26]
        assert result.data == [22, 24, 26], f"Got {result.data}"


# ======================================================================
# 5. Record transforms - basics (should pass)
# ======================================================================

class TestTransformBasics:

    def test_filter_records(self):
        records = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 17}]
        result = filter_records(records, lambda r: r['age'] >= 18)
        assert len(result) == 1
        assert result[0]['name'] == 'Alice'

    def test_sort_records(self):
        records = [
            {'name': 'Charlie', 'age': 25},
            {'name': 'Alice', 'age': 30},
            {'name': 'Bob', 'age': 20},
        ]
        result = sort_records(records, 'name')
        assert [r['name'] for r in result] == ['Alice', 'Bob', 'Charlie']

    def test_deduplicate_first(self):
        records = [
            {'id': 1, 'val': 'a'},
            {'id': 1, 'val': 'b'},
            {'id': 2, 'val': 'c'},
        ]
        result = deduplicate(records, 'id', keep='first')
        assert len(result) == 2
        assert result[0]['val'] == 'a'

    def test_map_fields(self):
        records = [{'first_name': 'Alice', 'last_name': 'Smith'}]
        result = map_fields(records, {'first_name': 'name'})
        assert result[0] == {'name': 'Alice', 'last_name': 'Smith'}

    def test_add_computed_field(self):
        records = [{'a': 1, 'b': 2}]
        result = add_computed_field(records, 'sum', lambda r: r['a'] + r['b'])
        assert result[0]['sum'] == 3


# ======================================================================
# 6. Record merging / joins (some fail due to outer-join bug)
# ======================================================================

class TestMergeRecords:

    def test_inner_join(self):
        left = [
            {'id': 1, 'name': 'Alice'},
            {'id': 2, 'name': 'Bob'},
            {'id': 3, 'name': 'Charlie'},
        ]
        right = [
            {'id': 1, 'score': 95},
            {'id': 2, 'score': 87},
            {'id': 4, 'score': 72},
        ]
        res = merge_records(left, right, on='id', how='inner')
        assert len(res) == 2
        assert res[0] == {'id': 1, 'name': 'Alice', 'score': 95}
        assert res[1] == {'id': 2, 'name': 'Bob', 'score': 87}

    def test_outer_join_right_fields_preserved(self):
        left = [{'id': 1, 'name': 'Alice'}]
        right = [
            {'id': 1, 'score': 95, 'grade': 'A'},
            {'id': 2, 'score': 87, 'grade': 'B'},
        ]
        res = merge_records(left, right, on='id', how='outer')
        unmatched = [r for r in res if r.get('id') == 2]
        assert len(unmatched) == 1
        rec = unmatched[0]
        assert 'score' in rec, f"Missing 'score': {rec}"
        assert rec['score'] == 87
        assert 'grade' in rec, f"Missing 'grade': {rec}"
        assert rec['grade'] == 'B'

    def test_outer_join_left_defaults(self):
        left = [{'id': 1, 'name': 'Alice', 'dept': 'Eng'}]
        right = [{'id': 2, 'score': 87, 'rank': 3}]
        res = merge_records(left, right, on='id', how='outer')
        ur = [r for r in res if r.get('id') == 2]
        assert len(ur) == 1
        rec = ur[0]
        assert rec.get('name') is None
        assert rec.get('dept') is None
        assert rec['score'] == 87
        assert rec['rank'] == 3


# ======================================================================
# 7. Formatter - plain text (should pass)
# ======================================================================

class TestFormatterPlain:

    def test_strip_simple_ansi(self):
        assert strip_ansi('\x1b[31mhello\x1b[0m') == 'hello'

    def test_colorize_basic(self):
        result = colorize('test', 'red')
        assert 'test' in result
        assert strip_ansi(result) == 'test'

    def test_table_no_colors(self):
        records = [{'name': 'Alice', 'age': 30}, {'name': 'Bob', 'age': 25}]
        fmt = TableFormatter(columns=[
            {'field': 'name', 'header': 'Name', 'width': 10},
            {'field': 'age', 'header': 'Age', 'width': 5},
        ])
        output = fmt.format_table(records)
        assert 'Alice' in output
        assert 'Bob' in output
        assert '30' in output

    def test_format_summary(self):
        records = [{'name': 'Alice', 'score': 95}, {'name': 'Bob', 'score': 87}]
        fmt = TableFormatter()
        summary = fmt.format_summary(records, {'score': 'avg'})
        assert 'score avg: 91.00' in summary


# ======================================================================
# 8. Formatter - ANSI (fail due to multi-param regex bug)
# ======================================================================

class TestFormatterANSI:

    def test_strip_multi_param_ansi(self):
        assert strip_ansi('\x1b[1;31mbold red\x1b[0m') == 'bold red'

    def test_visible_width_ignores_ansi(self):
        plain = 'hello'
        colored = colorize('hello', 'bold_red')
        assert visible_width(colored) == visible_width(plain) == 5

    def test_pad_to_width_with_ansi(self):
        colored = colorize('hi', 'bold_green')
        padded = pad_to_width(colored, 10)
        assert visible_width(padded) == 10
        assert strip_ansi(padded) == 'hi        '

    def test_table_alignment_with_colors(self):
        records = [
            {'name': 'Alice', 'status': 'active'},
            {'name': 'Bob', 'status': 'inactive'},
        ]
        fmt = TableFormatter(
            columns=[
                {'field': 'name', 'header': 'Name', 'width': 10},
                {'field': 'status', 'header': 'Status', 'width': 10},
            ],
            color_rules=[
                ('status', lambda r: r['status'] == 'active', 'bold_green'),
                ('status', lambda r: r['status'] == 'inactive', 'bold_red'),
            ],
        )
        output = fmt.format_table(records)
        lines = output.split('\n')
        hw = visible_width(lines[0])
        for line in lines[2:]:
            assert visible_width(line) == hw


# ======================================================================
# 9. Schema validation - basics (should pass)
# ======================================================================

class TestSchemaBasics:

    def test_basic_validation(self):
        sv = SchemaValidator({
            'name': {'type': 'string', 'required': True},
            'age': {'type': 'int', 'required': True, 'min': 0},
        })
        res, errs = sv.validate_record({'name': 'Alice', 'age': 30})
        assert not errs
        assert res['name'] == 'Alice'
        assert res['age'] == 30

    def test_required_field_with_default(self):
        sv = SchemaValidator({
            'name': {'type': 'string', 'required': True},
            'priority': {'type': 'int', 'required': True, 'default': 0},
        })
        res, errs = sv.validate_record({'name': 'Task1'})
        assert not errs
        assert res['priority'] == 0

    def test_coerce_string_to_int(self):
        sv = SchemaValidator({
            'count': {'type': 'int', 'required': True, 'coerce': True},
        })
        res, errs = sv.validate_record({'count': '42'}, coerce=True)
        assert not errs
        assert res['count'] == 42

    def test_choices_validation(self):
        sv = SchemaValidator({
            'color': {'type': 'string', 'required': True,
                      'choices': ['red', 'blue', 'green']},
        })
        res, errs = sv.validate_record({'color': 'red'})
        assert not errs
        assert res['color'] == 'red'
        res, errs = sv.validate_record({'color': 'purple'})
        assert len(errs) == 1

    def test_pattern_validation(self):
        sv = SchemaValidator({
            'email': {'type': 'string', 'required': True,
                      'pattern': r'^[\w.]+@[\w.]+$'},
        })
        res, errs = sv.validate_record({'email': 'user@example.com'})
        assert not errs
        res, errs = sv.validate_record({'email': 'not-an-email'})
        assert len(errs) == 1


# ======================================================================
# 10. Schema validation - defaults (fail due to missing-default bug)
# ======================================================================

class TestSchemaDefaults:

    def test_optional_field_default_applied(self):
        sv = SchemaValidator({
            'name': {'type': 'string', 'required': True},
            'role': {'type': 'string', 'required': False, 'default': 'viewer'},
            'active': {'type': 'bool', 'required': False, 'default': True},
        })
        res, errs = sv.validate_record({'name': 'Alice'})
        assert not errs, f"Unexpected errors: {errs}"
        assert 'role' in res, f"'role' default missing: {res}"
        assert res['role'] == 'viewer'
        assert 'active' in res, f"'active' default missing: {res}"
        assert res['active'] is True


# ======================================================================
# 11. Integration tests
# ======================================================================

class TestIntegration:

    def test_config_driven_label(self):
        cfg = PipelineConfig({
            'transform': {'filter_field': 'status', 'filter_value': 'active'},
            'output': {
                'label': 'Filtered by ${transform.filter_field}=${transform.filter_value}',
            },
        })
        assert cfg.resolve()['output']['label'] == (
            'Filtered by status=active'
        )

    def test_pipeline_schema_defaults(self):
        sv = SchemaValidator({
            'name': {'type': 'string', 'required': True},
            'score': {'type': 'float', 'required': True, 'min': 0, 'max': 100},
            'grade': {'type': 'string', 'required': False, 'default': 'N/A'},
        })

        def xform(data):
            return [{'name': r['name'], 'score': float(r['raw'])} for r in data]

        def validate_hook(result, stage):
            validated, _ = sv.validate_records(result.data)
            result.data = validated
            return result

        engine = PipelineEngine()
        engine.add_stage('xform', xform)
        engine.add_post_hook(validate_hook)
        out = engine.execute([
            {'name': 'Alice', 'raw': '95'},
            {'name': 'Bob', 'raw': '87'},
        ])
        for rec in out.data:
            assert 'grade' in rec, f"Missing default 'grade': {rec}"
            assert rec['grade'] == 'N/A'

    def test_merge_all_fields_present(self):
        users = [{'uid': 1, 'name': 'Alice'}, {'uid': 2, 'name': 'Bob'}]
        scores = [
            {'uid': 1, 'score': 95, 'level': 'expert'},
            {'uid': 3, 'score': 72, 'level': 'intermediate'},
        ]
        merged = merge_records(users, scores, on='uid', how='outer')
        all_fields = {'uid', 'name', 'score', 'level'}
        for rec in merged:
            for f in all_fields:
                assert f in rec, f"Missing '{f}' in {rec}"
