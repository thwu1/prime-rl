Build `/app/rdla_analyzer.py` — a Python tool that parses OpenMoonRay RDLA scene description files, extracts the scene graph, detects issues, and computes render complexity metrics.

## Usage

```
python3 /app/rdla_analyzer.py <scene_file.rdla>
```

Outputs JSON to stdout.

## RDLA Format

RDLA is a Lua-based scene description format used by DreamWorks' MoonRay renderer. Study the example scenes in `/app/scenes/` to understand the syntax. Key constructs:

- **Object declarations**: `TypeName("/path/name") { ... }`
- **SceneVariables**: `SceneVariables { ... }` — global singleton (no path)
- **Attributes**: `["attr_name"] = value`
- **Bindings**: `["attr"] = bind(TypeName("/target"))` — dependency edge from source to target
- **Object references**: `TypeName("/path")` in attribute values, table entries, or set memberships
- **Values**: numbers, `"strings"`, `true`/`false`, `Rgb(r,g,b)`, `Vec2(x,y)`, `Vec3(x,y,z)`
- **Transforms**: `translate(x,y,z)`, `rotate(x,y,z)`, `scale(x,y,z)`, chainable via `*`
- **Tables**: `{item1, item2, ...}`
- **Layer entries**: `{GeometryRef, "part", MaterialRef, LightSetRef}`
- **Comments**: `-- single line`

## Output JSON Format

```json
{
  "objects": [{"name": "/scene/obj", "type": "TypeName"}, ...],
  "bindings": [{"source": "/src", "attribute": "attr", "target": "/tgt"}, ...],
  "scene_variables": {"image_width": 512, "pixel_samples": 64, ...},
  "issues": [...],
  "complexity_score": 1234.56
}
```

Sort `objects` by name. Sort `bindings` by (source, attribute). Sort `issues` by (type, object/source). Include only scalar (numeric, string, boolean) scene variables.

## Issue Detection

Detect and report these issue types:

- **`circular_dependency`**: Cycles in the binding graph. Format: `{"type": "circular_dependency", "cycle": ["/obj_a", "/obj_b"]}`
- **`unresolved_reference`**: `bind()` target not defined as a scene object. Format: `{"type": "unresolved_reference", "source": "...", "attribute": "...", "target": "..."}`
- **`orphaned_object`**: Object not reachable from any `Layer` or `RenderOutput` via bindings, attribute references, and set/layer memberships. Format: `{"type": "orphaned_object", "object": "..."}`
- **`invalid_parameter`**: Constraint violations (see rules below). Format: `{"type": "invalid_parameter", "object": "...", "attribute": "...", "value": ..., "constraint": "..."}`

## Parameter Validation Rules

| Attribute | Applies to | Constraint |
|-----------|-----------|------------|
| `ior` | `DwaSolidDielectricMaterial`, `DwaRefractiveMaterial` | must be >= 1.0 |
| `roughness` | All material types | must be in [0.0, 1.0] |
| `intensity` | All light types | must be > 0 |
| `radius` | `SphereGeometry` | must be > 0 |

## Complexity Score

```
score = G × S × D^1.5 × (1 + 0.5·T) × (1 + 0.3·L)
```

- **G** = number of geometry objects
- **S** = `pixel_samples` from SceneVariables (default 8)
- **D** = `max_depth` from SceneVariables (default 5)
- **T** = number of transmissive material objects
- **L** = number of light objects

Round to 2 decimal places.

## Type Classifications

**Geometry**: `RdlMeshGeometry`, `BoxGeometry`, `SphereGeometry`, `UsdGeometry`, `RdlCurveGeometry`, `VdbGeometry`

**Light**: `RectLight`, `SphereLight`, `DiskLight`, `CylinderLight`, `DistantLight`, `EnvLight`, `SpotLight`, `MeshLight`

**Material**: `DwaBaseMaterial`, `DwaMetalMaterial`, `DwaSolidDielectricMaterial`, `DwaRefractiveMaterial`, `DwaFabricMaterial`, `DwaSkinMaterial`, `DwaClearcoatMaterial`, `DwaHairMaterial`, `DwaGlitterMaterial`, `DwaEmissiveMaterial`

**Transmissive** (subset of Material, for T in complexity): `DwaSolidDielectricMaterial`, `DwaRefractiveMaterial`