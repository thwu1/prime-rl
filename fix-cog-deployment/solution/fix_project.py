#!/usr/bin/env python3
"""
Fix broken Cog model project and generate OpenAPI 3.0.2 schema.

Reads the broken project, identifies specification violations,
writes corrected files, and generates the OpenAPI schema via AST analysis.

"""

import ast
import json
import os
import shutil
import sys

import yaml


# ============================================================
# Phase 1: Write corrected project files
# ============================================================

FIXED_COG_YAML = """\
build:
  python_version: "3.9"
  gpu: true
  python_requirements: requirements.txt
  system_packages:
    - ffmpeg
    - libgl1-mesa-glx
  sdk_version: "0.18.0"
run: "run.py:ImagePipeline"
"""

FIXED_RUN_PY = '''\
from cog import BaseRunner, Input, Path
from typing import Optional, List
from output_types import PipelineResult, ProcessingMetrics


class ImagePipeline(BaseRunner):
    def setup(self, weights=None):
        self.model = None
        self.device = "cuda"

    def run(
        self,
        image: Path = Input(description="Input image to process"),
        prompt: str = Input(description="Processing instruction"),
        style: str = Input(
            description="Visual style to apply",
            default="natural",
            choices=["natural", "artistic", "photorealistic", "abstract"]
        ),
        strength: float = Input(
            description="Effect strength",
            default=0.75,
            ge=0.0,
            le=1.0
        ),
        num_steps: int = Input(
            description="Number of processing steps",
            default=30,
            ge=1,
            le=150
        ),
        guidance_scale: float = Input(
            description="Classifier-free guidance scale",
            default=0.0,
            ge=0.0,
            le=20.0
        ),
        negative_prompt: Optional[str] = Input(
            description="Negative prompt",
            default=None
        ),
        seed: Optional[int] = Input(
            description="Random seed for reproducibility",
            default=None
        ),
        output_format: str = Input(
            description="Output image format",
            default="png",
            choices=["png", "jpeg", "webp"]
        ),
        tags: Optional[List[str]] = Input(
            description="Tags for the output",
            default=None
        ),
    ) -> PipelineResult:
        if self.model is None:
            raise RuntimeError("Model not loaded")
        result = PipelineResult(
            output_image=Path("/tmp/output.png"),
            metrics=ProcessingMetrics(
                processing_time=1.5,
                gpu_memory_used=2048.0,
                model_version="1.0.0"
            ),
            caption="Generated image",
            tags=tags or [],
            watermark=None
        )
        return result
'''

FIXED_OUTPUT_TYPES_PY = '''\
from cog import BaseModel, Path
from typing import List, Optional


class ProcessingMetrics(BaseModel):
    processing_time: float
    gpu_memory_used: float
    model_version: str


class PipelineResult(BaseModel):
    output_image: Path
    metrics: ProcessingMetrics
    caption: str
    tags: List[str]
    watermark: Optional[str] = None
'''


def write_file(path, content):
    """Write content to file with explicit flush and sync."""
    with open(path, 'w') as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def fix_project():
    """Apply all fixes to the project files."""
    # Remove output_types/ package directory if it exists (import shadowing)
    pkg_path = '/app/output_types'
    if os.path.isdir(pkg_path):
        shutil.rmtree(pkg_path)
        print("[fix] Removed output_types/ package directory (was shadowing output_types.py)")

    # Write corrected cog.yaml
    # Fixes: C1 (removed python_packages), C2 (sdk_version >= 0.16.0),
    #        C4+C5 (removed concurrency, predict→run migration)
    write_file('/app/cog.yaml', FIXED_COG_YAML)
    print("[fix] cog.yaml: removed python_packages, bumped sdk_version, "
          "removed concurrency (C4+C5 cascade), migrated predict->run")

    # Write corrected run.py
    # Fixes: R1 (removed duplicate method), R2 (non-Optional return),
    #        R3 (removed default_factory), R4 (fixed import path)
    write_file('/app/run.py', FIXED_RUN_PY)
    print("[fix] run.py: fixed import path, removed duplicate method, "
          "fixed return type, removed default_factory")

    # Write corrected output_types.py
    # Fixes: T1 (replaced Union[str, int] with str)
    write_file('/app/output_types.py', FIXED_OUTPUT_TYPES_PY)
    print("[fix] output_types.py: replaced Union[str, int] with str")


# ============================================================
# Phase 2: Generate OpenAPI 3.0.2 schema from fixed code
# ============================================================

def python_type_to_json_schema(annotation_node):
    """Convert a Python type annotation AST node to JSON Schema."""
    if isinstance(annotation_node, ast.Name):
        type_map = {
            'str': {'type': 'string'},
            'int': {'type': 'integer'},
            'float': {'type': 'number'},
            'bool': {'type': 'boolean'},
            'Path': {'type': 'string', 'format': 'uri'},
            'Secret': {'type': 'string', 'format': 'password', 'x-cog-secret': True},
        }
        return type_map.get(annotation_node.id, {'type': 'object'})

    if isinstance(annotation_node, ast.Subscript):
        if isinstance(annotation_node.value, ast.Name):
            name = annotation_node.value.id
            if name == 'Optional':
                return python_type_to_json_schema(annotation_node.slice)
            elif name in ('List', 'list'):
                items = python_type_to_json_schema(annotation_node.slice)
                return {'type': 'array', 'items': items}
            elif name in ('Dict', 'dict'):
                return {'type': 'object'}

    if isinstance(annotation_node, ast.Attribute):
        if annotation_node.attr == 'Path':
            return {'type': 'string', 'format': 'uri'}

    return {'type': 'object'}


def is_optional_type(annotation_node):
    """Check if a type annotation represents Optional[T]."""
    if isinstance(annotation_node, ast.Subscript):
        if isinstance(annotation_node.value, ast.Name):
            return annotation_node.value.id == 'Optional'
    return False


def extract_input_metadata(default_node):
    """Extract metadata from an Input() call's keyword arguments.

    Uses identity check against None (not truthiness) to correctly
    preserve falsy defaults like 0, 0.0, False, or empty string.
    """
    meta = {}
    if not isinstance(default_node, ast.Call):
        return meta

    for kw in default_node.keywords:
        if kw.arg == 'description':
            meta['description'] = ast.literal_eval(kw.value)
        elif kw.arg == 'default':
            val = ast.literal_eval(kw.value)
            # Use identity check: 0.0 is falsy but is not None
            if val is not None:
                meta['default'] = val
        elif kw.arg == 'ge':
            meta['minimum'] = ast.literal_eval(kw.value)
        elif kw.arg == 'le':
            meta['maximum'] = ast.literal_eval(kw.value)
        elif kw.arg == 'choices':
            meta['enum'] = ast.literal_eval(kw.value)

    return meta


def field_name_to_title(name):
    """Convert snake_case field name to Title Case for schema titles."""
    return ' '.join(word.capitalize() for word in name.split('_'))


PRIMITIVE_TYPE_NAMES = frozenset({
    'str', 'int', 'float', 'bool', 'Path', 'Secret',
    'dict', 'Dict', 'Any', 'list', 'List',
})


def parse_base_model_to_schema(cls_node):
    """Parse a BaseModel class definition into a JSON Schema object."""
    properties = {}
    required = []

    for item in cls_node.body:
        if not isinstance(item, ast.AnnAssign):
            continue
        if not isinstance(item.target, ast.Name):
            continue

        field_name = item.target.id
        annotation = item.annotation

        # Check if the type is a reference to another BaseModel
        if (isinstance(annotation, ast.Name)
                and annotation.id not in PRIMITIVE_TYPE_NAMES):
            properties[field_name] = {
                '$ref': f'#/components/schemas/{annotation.id}'
            }
        else:
            json_type = python_type_to_json_schema(annotation)
            prop = dict(json_type)
            prop['title'] = field_name_to_title(field_name)
            properties[field_name] = prop

        # Optional fields are NOT required
        if not is_optional_type(annotation):
            required.append(field_name)

    return {
        'type': 'object',
        'properties': properties,
        'required': required
    }


def generate_schema():
    """Generate OpenAPI 3.0.2 schema from the fixed model code."""
    # --- Parse run.py ---
    with open('/app/run.py') as f:
        run_source = f.read()
    run_tree = ast.parse(run_source)

    # Find the runner class
    runner_class = None
    for node in ast.walk(run_tree):
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                base_name = None
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr
                if base_name in ('BaseRunner', 'BasePredictor'):
                    runner_class = node
                    break
            if runner_class:
                break

    if not runner_class:
        print("ERROR: No runner class found in run.py", file=sys.stderr)
        sys.exit(1)

    # Find the inference method
    method = None
    for item in runner_class.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name in ('run', 'predict'):
                method = item
                break

    if not method:
        print("ERROR: No run()/predict() method found", file=sys.stderr)
        sys.exit(1)

    # --- Extract input schema ---
    input_properties = {}
    required_inputs = []

    params = method.args.args[1:]  # Skip 'self'
    defaults = method.args.defaults
    num_no_default = len(params) - len(defaults)
    padded_defaults = [None] * num_no_default + list(defaults)

    for i, (param, default) in enumerate(zip(params, padded_defaults)):
        name = param.arg
        annotation = param.annotation

        json_type = python_type_to_json_schema(annotation)
        input_meta = extract_input_metadata(default)

        prop = dict(json_type)
        prop.update(input_meta)
        prop['x-order'] = i

        input_properties[name] = prop

        is_opt = is_optional_type(annotation)
        has_default = (isinstance(default, ast.Call) and
                       any(kw.arg == 'default' for kw in default.keywords))

        if not is_opt and not has_default:
            required_inputs.append(name)

    # --- Parse output types ---
    with open('/app/output_types.py') as f:
        out_source = f.read()
    out_tree = ast.parse(out_source)

    model_schemas = {}
    for node in ast.walk(out_tree):
        if isinstance(node, ast.ClassDef):
            bases = []
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
                elif isinstance(b, ast.Attribute):
                    bases.append(b.attr)
            if 'BaseModel' in bases:
                schema = parse_base_model_to_schema(node)
                schema['title'] = node.name
                model_schemas[node.name] = schema

    # Determine output type from method return annotation
    output_type_name = None
    if isinstance(method.returns, ast.Name):
        output_type_name = method.returns.id

    # --- Build component schemas ---
    component_schemas = {
        'Input': {
            'title': 'Input',
            'type': 'object',
            'properties': input_properties,
            'required': required_inputs
        }
    }

    # Add output and nested model schemas
    if output_type_name and output_type_name in model_schemas:
        component_schemas['Output'] = dict(model_schemas[output_type_name])
        for name, schema in model_schemas.items():
            if name != output_type_name:
                component_schemas[name] = schema

    # Add prediction envelopes (Section 4.2)
    component_schemas['PredictionRequest'] = {
        'title': 'PredictionRequest',
        'type': 'object',
        'properties': {
            'id': {'type': 'string', 'title': 'Id'},
            'input': {'$ref': '#/components/schemas/Input'}
        }
    }

    component_schemas['PredictionResponse'] = {
        'title': 'PredictionResponse',
        'type': 'object',
        'properties': {
            'id': {'type': 'string', 'title': 'Id'},
            'input': {'$ref': '#/components/schemas/Input'},
            'output': {'$ref': '#/components/schemas/Output'},
            'status': {'type': 'string', 'title': 'Status'},
            'error': {'type': 'string', 'title': 'Error'},
            'logs': {'type': 'string', 'title': 'Logs', 'default': ''}
        }
    }

    # --- Write OpenAPI document ---
    openapi_schema = {
        'openapi': '3.0.2',
        'info': {'title': 'Cog', 'version': '0.1.0'},
        'paths': {
            '/predictions': {
                'post': {
                    'summary': 'Predict',
                    'operationId': 'predict_predictions_post',
                    'requestBody': {
                        'content': {
                            'application/json': {
                                'schema': {
                                    '$ref': '#/components/schemas/PredictionRequest'
                                }
                            }
                        }
                    },
                    'responses': {
                        '200': {
                            'description': 'Successful Response',
                            'content': {
                                'application/json': {
                                    'schema': {
                                        '$ref': '#/components/schemas/PredictionResponse'
                                    }
                                }
                            }
                        }
                    }
                }
            }
        },
        'components': {
            'schemas': component_schemas
        }
    }

    write_file('/app/openapi_schema.json', json.dumps(openapi_schema, indent=2) + '\n')

    print(f"[schema] Generated openapi_schema.json with "
          f"{len(component_schemas)} component schemas")


# ============================================================
# Main
# ============================================================

if __name__ == '__main__':
    fix_project()
    generate_schema()
    print("\nAll fixes applied and schema generated successfully.")
