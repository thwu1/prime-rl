# Cog Framework Specification Reference

This document specifies the rules and constraints that a valid Cog (Replicate) model project must satisfy. A Cog project consists of a configuration file (`cog.yaml`), a runner module (Python), and optionally additional type definition modules.

## 1. Configuration (`cog.yaml`)

### 1.1 Build Section

- `build.python_version` (string): Python interpreter version. Supported: `"3.8"` through `"3.13"`.
- `build.gpu` (bool): Enable CUDA/GPU support. Determines base image selection and triggers CUDA version resolution.
- `build.cuda` (string): Explicit CUDA version override (auto-detected from PyTorch version when `gpu: true` and omitted).
- `build.python_packages` (list of strings): Inline pip package specifications (e.g., `["torch==2.1.0", "Pillow>=10.0"]`).
- `build.python_requirements` (string): Path to a `requirements.txt` file relative to the project root.
  - **Rule C1**: `python_packages` and `python_requirements` are **mutually exclusive**. Setting both is a configuration validation error. Use one or the other.
- `build.system_packages` (list of strings): System packages installed via `apt-get`.
- `build.pre_install` (list of strings): Shell commands run before `pip install` during image build.
- `build.run` (list): Arbitrary shell commands (strings or objects with `command` and `mounts` keys) run during build.
- `build.sdk_version` (string): Cog SDK version to embed in the image.
  - **Rule C2**: When using `BaseRunner`, the SDK version must be `>= 0.16.0`. The `BaseRunner` API was introduced in SDK 0.16.0; earlier versions only support the legacy `BasePredictor` interface.
  - If omitted, the latest compatible SDK version is used automatically.

### 1.2 Entry Points

- `run` (string): Module and class reference in `"module.py:ClassName"` format. Points to the runner class for inference.
- `predict` (string): Deprecated alias for `run`. Functionally identical but triggers a deprecation warning. Projects should migrate from `predict` to `run`.
- `train` (string): Optional training entry point in the same `"module.py:ClassName"` format.
  - **Rule C3**: If both `run` and `predict` are set in the same config, `predict` is silently ignored. Prefer using `run` exclusively.

### 1.3 Concurrency

- `concurrency.max` (int): Maximum concurrent prediction slots. Default: `1`.
  - **Rule C4**: Values greater than 1 require the inference method (`run()` or `predict()`) to be declared `async def`. Synchronous methods process one request at a time and cannot handle concurrent slots.
  - **Rule C5**: Async runners require `python_version >= "3.11"`. Earlier Python versions lack required async generator features.

### 1.4 Image

- `image` (string): Custom base Docker image override. When set, Cog uses this as the base instead of auto-selecting one.
  - Must include Python at the version specified by `python_version`.

### 1.5 Weights

- `build.weights` (list of objects): Managed weight sources downloaded during build.
  - Each entry has `source` (URL), `dest` (path in container), and optional `type`.

## 2. Runner API

### 2.1 Class Definition

- The runner class **must** extend `cog.BaseRunner` (preferred) or `cog.BasePredictor` (legacy, deprecated).
- `BasePredictor` is a backward-compatibility alias for `BaseRunner`. Both provide the same interface.
- Only one runner class should be defined per module file.

### 2.2 Methods

- `setup(self, weights=None)`: Called exactly once when the container starts. Used to load model weights, initialize GPU resources, and prepare any state shared across predictions. The optional `weights` parameter receives the value from the `COG_WEIGHTS` environment variable when set.
- `run(self, **kwargs)` or `predict(self, **kwargs)`: Called for each prediction request.
  - **Rule R1**: Exactly one of `run()` or `predict()` must be defined in the runner class. Defining both is a validation error — Cog's dispatch logic cannot determine which method to invoke.
  - Parameters (after `self`) must use type annotations with `cog.Input()` as the default value descriptor.
  - The method may be synchronous (`def`) or asynchronous (`async def`). Async methods enable concurrent prediction handling when `concurrency.max > 1`.

### 2.3 Return Type

- The inference method's return type annotation determines the output schema structure.
- **Rule R2**: The return type **cannot** be `Optional[T]`. In Cog's prediction model, a prediction either succeeds and returns a value, or fails by raising an exception. There is no concept of a "null" successful prediction.
- Supported return types:
  - Primitives: `str`, `int`, `float`, `bool`
  - Files: `cog.Path` (file is uploaded to storage and returned as a URL)
  - Structured: Any `pydantic.BaseModel` subclass (serialized as a JSON object)
  - Streaming: `Iterator[T]`, `AsyncIterator[T]` (values yielded incrementally)
  - Concatenated streaming: `ConcatenateIterator` (for token-by-token text streaming)
  - Collections: `list[T]`, `dict`

### 2.4 Input Parameters

- Each parameter of the inference method (after `self`) defines one model input.
- Must have a type annotation and a `cog.Input()` call as its default value.
- `cog.Input()` supported keyword arguments:
  - `description` (str): Human-readable description shown in API docs and UI.
  - `default` (any): Default value. Set to `None` for optional inputs.
  - `ge` / `le` (number): Numeric constraints: greater-than-or-equal / less-than-or-equal.
  - `gt` / `lt` (number): Strict numeric constraints (less common).
  - `min_length` / `max_length` (int): String length constraints.
  - `choices` (list): Enumeration of the only allowed values.
  - `regex` (str): Regular expression pattern constraint for string inputs.
  - **Rule R3**: `default_factory` is **not** a supported `Input()` keyword. Cog's static schema generator performs AST-level analysis of `Input()` calls without executing Python code, so factory callables cannot be evaluated. For optional collection-type parameters, use `Optional[List[T]]` with `default=None` instead.

### 2.5 Import Resolution

- **Rule R4**: All `import` and `from ... import` statements in the runner module must resolve to existing files on disk. Cog's schema generator performs static cross-file analysis to resolve `BaseModel` definitions and type references.
- Resolution rules:
  - `from foo.bar import X` resolves to `foo/bar.py` or `foo/bar/__init__.py` relative to the project root.
  - `from bar import X` resolves to `bar.py` or `bar/__init__.py` in the project root.
  - Unresolvable imports cause schema generation to fail.

## 3. Type System for Schema Generation

Cog generates OpenAPI schemas via **static analysis** (Go-based tree-sitter parser in production, AST-based in development). No Python code is executed during schema generation. This imposes strict constraints on which type annotations are supported.

### 3.1 Input Type Mappings

| Python Type | JSON Schema |
|---|---|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `cog.Path` | `{"type": "string", "format": "uri"}` |
| `cog.Secret` | `{"type": "string", "format": "password", "x-cog-secret": true}` |
| `Optional[T]` | Unwrapped to T's schema; parameter excluded from `required` |
| `List[T]` / `list[T]` | `{"type": "array", "items": <T's schema>}` |

### 3.2 Output Type Mappings

- Primitives and `cog.Path` map identically to input types.
- `BaseModel` subclasses map to `{"type": "object"}` with `properties` derived from annotated class fields:
  - Fields whose type is another `BaseModel` subclass produce `{"$ref": "#/components/schemas/ClassName"}`.
  - Fields with primitive types produce inline type definitions. Each such property includes a `title` field derived from the field name: snake_case is converted to Title Case (underscores become spaces, each word capitalized).
- `dict` maps to `{"type": "object"}` (unstructured).
- `list[T]` / `List[T]` maps to `{"type": "array", "items": <T's schema>}`.
- **Rule T1**: `Union[A, B]` where **neither** `A` nor `B` is `None` is **not supported**. The static schema generator cannot determine which type to select at build time. Only `Optional[T]` (i.e., `Union[T, None]`) is allowed as a union form.

### 3.3 BaseModel Field Resolution

- Fields are extracted from class-level annotated assignments (`field_name: Type` or `field_name: Type = default_value`).
- All non-`Optional` fields are included in the schema's `required` array.
- Cross-file `BaseModel` references are resolved by tracking imports from the runner module.
- Circular references between `BaseModel` classes are not supported.

## 4. OpenAPI Schema Structure

Cog generates an OpenAPI 3.0.2 specification from static analysis. The schema is embedded as a Docker label during `cog build` and served at runtime via `GET /openapi.json`.

### 4.1 Document Structure

```json
{
  "openapi": "3.0.2",
  "info": {"title": "Cog", "version": "0.1.0"},
  "paths": {
    "/predictions": {
      "post": {
        "summary": "Predict",
        "operationId": "predict_predictions_post",
        "requestBody": {
          "content": {
            "application/json": {
              "schema": {"$ref": "#/components/schemas/PredictionRequest"}
            }
          }
        },
        "responses": {
          "200": {
            "description": "Successful Response",
            "content": {
              "application/json": {
                "schema": {"$ref": "#/components/schemas/PredictionResponse"}
              }
            }
          }
        }
      }
    }
  },
  "components": {
    "schemas": { ... }
  }
}
```

### 4.2 Component Schemas

**Input**: Object schema with properties derived from inference method parameters.
- Each parameter produces a property with the mapped JSON Schema type from Section 3.1.
- `Input()` metadata maps to JSON Schema keywords:
  - `description` → `description`
  - `default` → `default` (omitted when value is `None`)
  - `ge` → `minimum`
  - `le` → `maximum`
  - `choices` → `enum`
- Each property includes an `x-order` field (integer) matching the parameter's positional index (0-based).
- The `required` array lists parameters that have no `default` value and whose type is not `Optional`.

**Output**: Object schema derived from the return type. If the return type is a `BaseModel` subclass, its schema is included as a component (using the class name or "Output").

**Nested BaseModel schemas**: Each `BaseModel` subclass referenced (directly or transitively) by the output type is included as a separate component schema, keyed by its class name.

**PredictionRequest**: Prediction envelope with properties:
- `id` (string): Prediction identifier
- `input` ($ref to Input schema)

**PredictionResponse**: Response envelope with properties:
- `id` (string): Prediction identifier
- `input` ($ref to Input schema)
- `output` ($ref to Output schema)
- `status` (string): Prediction status
- `error` (string): Error message if failed
- `logs` (string, default: ""): Captured stdout/stderr

## 5. HTTP API

The Cog HTTP server exposes these endpoints (for reference):

- `POST /predictions` — Create a prediction (sync or async with webhook)
- `PUT /predictions/{id}` — Idempotent create-or-get
- `POST /predictions/{id}/cancel` — Cancel a running prediction
- `GET /health-check` — Container health status
- `GET /openapi.json` — Generated OpenAPI schema
- `GET /` — Root redirect to docs
