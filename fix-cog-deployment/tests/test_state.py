"""
Tests for Cog model project compliance and OpenAPI schema generation.

Validates that all specification violations are resolved, the module layout
is unambiguous, and the generated OpenAPI 3.0.2 schema correctly reflects
Cog's type mapping rules including edge cases.

"""

import ast
import json
import os
import sys

import yaml
import pytest


# ============================================================
# Test Suite 1: cog.yaml configuration validation
# ============================================================

class TestCogYaml:
    """Verify cog.yaml configuration violations are resolved."""

    @pytest.fixture(autouse=True)
    def load_config(self):
        with open('/app/cog.yaml') as f:
            self.config = yaml.safe_load(f)

    def test_no_dual_package_specs(self):
        """Rule C1: python_packages and python_requirements are mutually exclusive."""
        build = self.config.get('build', {})
        has_packages = bool(build.get('python_packages'))
        has_requirements = bool(build.get('python_requirements'))
        assert not (has_packages and has_requirements), \
            "cog.yaml cannot have both python_packages and python_requirements (Rule C1)"

    def test_sdk_version_minimum(self):
        """Rule C2: sdk_version must be >= 0.16.0 when using BaseRunner."""
        build = self.config.get('build', {})
        sdk = build.get('sdk_version', '')
        if sdk:
            clean = sdk.split('a')[0].split('b')[0].split('rc')[0]
            parts = clean.split('.')
            major, minor = int(parts[0]), int(parts[1])
            assert (major, minor) >= (0, 16), \
                f"sdk_version {sdk} is below minimum 0.16.0 required for BaseRunner (Rule C2)"

    def test_concurrency_requires_async(self):
        """Rule C4: concurrency.max > 1 requires async inference method."""
        conc = self.config.get('concurrency', {})
        max_conc = conc.get('max', 1) if conc else 1

        if max_conc > 1:
            predict_ref = self.config.get('run') or self.config.get('predict', '')
            if ':' in str(predict_ref):
                module_path = predict_ref.split(':')[0]
                full_path = os.path.join('/app', module_path)
                with open(full_path) as f:
                    source = f.read()
                tree = ast.parse(source)

                has_async = False
                for node in ast.walk(tree):
                    if isinstance(node, ast.AsyncFunctionDef) and node.name in ('run', 'predict'):
                        has_async = True
                        break

                assert has_async, \
                    "concurrency.max > 1 requires an async def run()/predict() method (Rule C4)"

    def test_concurrency_python_version_consistency(self):
        """Rule C5: async runners require python_version >= 3.11."""
        conc = self.config.get('concurrency', {})
        max_conc = conc.get('max', 1) if conc else 1

        if max_conc > 1:
            build = self.config.get('build', {})
            py_ver = build.get('python_version', '3.8')
            parts = py_ver.split('.')
            major, minor = int(parts[0]), int(parts[1])
            assert (major, minor) >= (3, 11), \
                f"concurrency.max={max_conc} requires async, which requires " \
                f"python_version >= 3.11 (Rule C5), but got {py_ver}"


# ============================================================
# Test Suite 2: run.py API contract validation
# ============================================================

class TestRunPy:
    """Verify run.py API contract violations are resolved."""

    @pytest.fixture(autouse=True)
    def load_source(self):
        with open('/app/run.py') as f:
            self.source = f.read()
        self.tree = ast.parse(self.source)

        self.runner_class = None
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name = None
                    if isinstance(base, ast.Name):
                        base_name = base.id
                    elif isinstance(base, ast.Attribute):
                        base_name = base.attr
                    if base_name in ('BaseRunner', 'BasePredictor'):
                        self.runner_class = node
                        break

    def test_runner_class_exists(self):
        """A class extending BaseRunner or BasePredictor must exist."""
        assert self.runner_class is not None, \
            "No class extending BaseRunner or BasePredictor found in run.py"

    def test_no_dual_methods(self):
        """Rule R1: exactly one of run() or predict() must be defined."""
        assert self.runner_class is not None
        methods = set()
        for item in self.runner_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in ('run', 'predict'):
                    methods.add(item.name)
        assert len(methods) == 1, \
            f"Must have exactly one of run()/predict(), found: {methods} (Rule R1)"

    def test_output_not_optional(self):
        """Rule R2: return type cannot be Optional."""
        assert self.runner_class is not None
        method = None
        for item in self.runner_class.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in ('run', 'predict'):
                    method = item
                    break
        assert method is not None

        ret = method.returns
        if ret is not None:
            if isinstance(ret, ast.Subscript):
                val = ret.value
                name = None
                if isinstance(val, ast.Name):
                    name = val.id
                elif isinstance(val, ast.Attribute):
                    name = val.attr
                assert name != 'Optional', \
                    "Return type cannot be Optional — predictions must succeed or fail (Rule R2)"

    def test_no_default_factory(self):
        """Rule R3: default_factory is not supported in cog.Input()."""
        assert 'default_factory' not in self.source, \
            "default_factory is not supported by Cog's static schema generator (Rule R3)"

    def test_import_resolves(self):
        """Rule R4: imports referencing output_types must resolve to existing files."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if 'output_types' in node.module:
                    module = node.module
                    parts = module.split('.')

                    file_path = os.path.join('/app', *parts) + '.py'
                    pkg_path = os.path.join('/app', *parts, '__init__.py')

                    assert os.path.exists(file_path) or os.path.exists(pkg_path), \
                        f"Import '{module}' cannot resolve — no file at {file_path} " \
                        f"or {pkg_path} (Rule R4)"

    def test_no_import_shadowing(self):
        """Module imports must not be ambiguous due to same-named package directories."""
        for node in ast.walk(self.tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split('.')
                base = parts[0]
                file_path = os.path.join('/app', base + '.py')
                pkg_path = os.path.join('/app', base)

                if os.path.isfile(file_path) and os.path.isdir(pkg_path):
                    pytest.fail(
                        f"Import '{node.module}' is ambiguous: both '{base}.py' and "
                        f"'{base}/' exist. Python resolves to the package, which may "
                        f"have different definitions, causing silent schema errors."
                    )


# ============================================================
# Test Suite 3: output_types.py type annotation validation
# ============================================================

class TestOutputTypes:
    """Verify output type annotation violations are resolved."""

    def test_no_unsupported_union(self):
        """Rule T1: Union[A, B] where neither is None is not supported."""
        with open('/app/output_types.py') as f:
            source = f.read()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                ann = node.annotation
                if isinstance(ann, ast.Subscript) and isinstance(ann.value, ast.Name):
                    if ann.value.id == 'Union':
                        if isinstance(ann.slice, ast.Tuple):
                            elts = ann.slice.elts
                            has_none = any(
                                (isinstance(e, ast.Constant) and e.value is None) or
                                (isinstance(e, ast.Name) and e.id == 'None')
                                for e in elts
                            )
                            if not has_none:
                                field_name = node.target.id
                                type_names = []
                                for e in elts:
                                    if isinstance(e, ast.Name):
                                        type_names.append(e.id)
                                    else:
                                        type_names.append(ast.dump(e))
                                pytest.fail(
                                    f"Field '{field_name}' uses Union[{', '.join(type_names)}] "
                                    f"which cannot be statically resolved (Rule T1)"
                                )


# ============================================================
# Test Suite 4: OpenAPI schema validation
# ============================================================

class TestSchema:
    """Verify the generated OpenAPI schema is correct."""

    @pytest.fixture(autouse=True)
    def load_schema(self):
        assert os.path.exists('/app/openapi_schema.json'), \
            "openapi_schema.json not found — must be generated at /app/openapi_schema.json"
        with open('/app/openapi_schema.json') as f:
            self.schema = json.load(f)
        self.components = self.schema.get('components', {}).get('schemas', {})

    def test_openapi_version(self):
        """Schema must use OpenAPI 3.0.2."""
        assert self.schema.get('openapi') == '3.0.2', \
            f"Expected OpenAPI 3.0.2, got {self.schema.get('openapi')}"

    def test_info_title(self):
        """Schema info title must be 'Cog'."""
        info = self.schema.get('info', {})
        assert info.get('title') == 'Cog', \
            f"Expected info.title='Cog', got {info.get('title')}"

    def test_input_schema_exists(self):
        """Input schema must exist in components."""
        assert 'Input' in self.components, "Input schema not found in components"

    def test_input_properties_types(self):
        """Each input property must have the correct JSON Schema type."""
        input_schema = self.components['Input']
        props = input_schema.get('properties', {})

        expected_types = {
            'image': ('string', 'uri'),
            'prompt': ('string', None),
            'style': ('string', None),
            'strength': ('number', None),
            'num_steps': ('integer', None),
            'guidance_scale': ('number', None),
            'negative_prompt': ('string', None),
            'seed': ('integer', None),
            'output_format': ('string', None),
            'tags': ('array', None),
        }

        for name, (expected_type, expected_format) in expected_types.items():
            assert name in props, f"Missing input property: {name}"
            assert props[name].get('type') == expected_type, \
                f"Input '{name}': expected type={expected_type}, got {props[name].get('type')}"
            if expected_format:
                assert props[name].get('format') == expected_format, \
                    f"Input '{name}': expected format={expected_format}, got {props[name].get('format')}"

    def test_input_required_fields(self):
        """Only 'image' and 'prompt' should be required."""
        input_schema = self.components['Input']
        required = set(input_schema.get('required', []))
        assert required == {'image', 'prompt'}, \
            f"Expected required={{'image', 'prompt'}}, got {sorted(required)}"

    def test_input_x_order(self):
        """Input properties must have x-order matching parameter position."""
        input_schema = self.components['Input']
        props = input_schema.get('properties', {})

        expected_order = [
            'image', 'prompt', 'style', 'strength', 'num_steps',
            'guidance_scale', 'negative_prompt', 'seed', 'output_format', 'tags'
        ]
        for i, name in enumerate(expected_order):
            assert name in props, f"Missing property: {name}"
            assert props[name].get('x-order') == i, \
                f"Input '{name}': expected x-order={i}, got {props[name].get('x-order')}"

    def test_input_constraints(self):
        """Numeric constraints and choice enums must be correctly mapped."""
        input_schema = self.components['Input']
        props = input_schema.get('properties', {})

        assert props['strength'].get('minimum') == 0.0, \
            f"strength minimum should be 0.0, got {props['strength'].get('minimum')}"
        assert props['strength'].get('maximum') == 1.0, \
            f"strength maximum should be 1.0, got {props['strength'].get('maximum')}"

        assert props['num_steps'].get('minimum') == 1, \
            f"num_steps minimum should be 1, got {props['num_steps'].get('minimum')}"
        assert props['num_steps'].get('maximum') == 150, \
            f"num_steps maximum should be 150, got {props['num_steps'].get('maximum')}"

        assert props['guidance_scale'].get('minimum') == 0.0, \
            f"guidance_scale minimum should be 0.0, got {props['guidance_scale'].get('minimum')}"
        assert props['guidance_scale'].get('maximum') == 20.0, \
            f"guidance_scale maximum should be 20.0, got {props['guidance_scale'].get('maximum')}"

        assert props['style'].get('enum') == ['natural', 'artistic', 'photorealistic', 'abstract'], \
            f"style enum mismatch: {props['style'].get('enum')}"

        assert props['output_format'].get('enum') == ['png', 'jpeg', 'webp'], \
            f"output_format enum mismatch: {props['output_format'].get('enum')}"

    def test_input_defaults(self):
        """Default values must be correctly mapped, including falsy non-None values."""
        input_schema = self.components['Input']
        props = input_schema.get('properties', {})

        assert props['style'].get('default') == 'natural'
        assert props['strength'].get('default') == 0.75
        assert props['num_steps'].get('default') == 30
        assert props['output_format'].get('default') == 'png'

        # guidance_scale has default=0.0 — falsy but not None, must be preserved
        assert 'default' in props.get('guidance_scale', {}), \
            "guidance_scale has default=0.0 which must appear in schema (0.0 is falsy but not None)"
        assert props['guidance_scale']['default'] == 0.0, \
            f"guidance_scale default should be 0.0, got {props['guidance_scale'].get('default')}"

    def test_tags_items(self):
        """Tags must be array with string items."""
        input_schema = self.components['Input']
        props = input_schema.get('properties', {})
        tags = props.get('tags', {})
        assert tags.get('type') == 'array'
        items = tags.get('items', {})
        assert items.get('type') == 'string', \
            f"tags.items should be string, got {items}"

    def test_output_schema_exists(self):
        """Output or PipelineResult schema must exist."""
        output_names = {'Output', 'PipelineResult'}
        found = output_names & set(self.components.keys())
        assert found, \
            f"No output schema found in components. Expected one of: {output_names}"

    def test_output_schema_fields(self):
        """Output schema must have correct field types including watermark."""
        output = self.components.get('Output') or self.components.get('PipelineResult')
        assert output is not None, "Output schema not found"

        props = output.get('properties', {})

        assert 'output_image' in props, "output_image missing from output schema"
        img = props['output_image']
        if '$ref' not in img:
            assert img.get('type') == 'string', f"output_image type should be string"
            assert img.get('format') == 'uri', f"output_image format should be uri"

        assert 'caption' in props, "caption missing from output schema"
        cap = props['caption']
        if '$ref' not in cap:
            assert cap.get('type') == 'string', \
                f"caption should be type=string (not Union), got {cap}"

        assert 'tags' in props, "tags missing from output schema"
        tags = props['tags']
        if '$ref' not in tags:
            assert tags.get('type') == 'array', f"tags should be array"

        assert 'metrics' in props, "metrics missing from output schema"

        assert 'watermark' in props, "watermark missing from output schema"
        wm = props['watermark']
        if '$ref' not in wm:
            assert wm.get('type') == 'string', \
                f"watermark should be type=string, got {wm}"

    def test_output_required_fields(self):
        """Optional fields must not be in required array."""
        output = self.components.get('Output') or self.components.get('PipelineResult')
        assert output is not None, "Output schema not found"
        required = set(output.get('required', []))

        assert 'watermark' not in required, \
            "watermark is Optional[str] with default None — must not be in required"

        for field in ('output_image', 'metrics', 'caption', 'tags'):
            assert field in required, \
                f"Non-optional field '{field}' must be in output required array"

    def test_processing_metrics_schema(self):
        """ProcessingMetrics must exist with correct field types."""
        if 'ProcessingMetrics' in self.components:
            pm = self.components['ProcessingMetrics']
            props = pm.get('properties', {})

            assert 'processing_time' in props, "processing_time missing"
            assert 'gpu_memory_used' in props, "gpu_memory_used missing"
            assert 'model_version' in props, "model_version missing"

            assert props['processing_time'].get('type') == 'number', \
                f"processing_time should be number (float), got {props['processing_time'].get('type')}"
            assert props['gpu_memory_used'].get('type') == 'number', \
                f"gpu_memory_used should be number (float), got {props['gpu_memory_used'].get('type')}"
            assert props['model_version'].get('type') == 'string'
        else:
            output = self.components.get('Output') or self.components.get('PipelineResult')
            assert output is not None
            props = output.get('properties', {})
            metrics = props.get('metrics', {})

            if 'properties' in metrics:
                m_props = metrics['properties']
                assert 'processing_time' in m_props
                assert 'gpu_memory_used' in m_props
                assert 'model_version' in m_props
                assert m_props['processing_time'].get('type') == 'number', \
                    "processing_time should be number (float)"
            else:
                pytest.fail("ProcessingMetrics not found as component or inlined")

    def test_prediction_envelope(self):
        """Schema must include PredictionRequest and PredictionResponse."""
        assert 'PredictionRequest' in self.components, \
            "PredictionRequest schema missing from components"
        assert 'PredictionResponse' in self.components, \
            "PredictionResponse schema missing from components"

        req = self.components['PredictionRequest']
        req_props = req.get('properties', {})
        assert 'input' in req_props, "PredictionRequest must have 'input' property"

        resp = self.components['PredictionResponse']
        resp_props = resp.get('properties', {})
        assert 'output' in resp_props, "PredictionResponse must have 'output' property"
        assert 'status' in resp_props, "PredictionResponse must have 'status' property"
