# WebGL 1.0 / OpenGL ES 2.0 — Conformance Validation Reference

Specification excerpts relevant to the conformance validation pipeline.
Section numbers reference the OpenGL ES 2.0 Full Specification (Revision 2.0.25)
and the WebGL 1.0 Specification.

---

## 1. Texture Object Default State (GLES2 Table 3.10)

When a texture object is first created, its state is initialized as follows:

| Parameter            | Initial Value            | Constant                 |
|----------------------|--------------------------|--------------------------|
| `TEXTURE_MIN_FILTER` | `NEAREST_MIPMAP_LINEAR`  | `0x2702`                 |
| `TEXTURE_MAG_FILTER` | `LINEAR`                 | `0x2601`                 |
| `TEXTURE_WRAP_S`     | `REPEAT`                 | `0x2901`                 |
| `TEXTURE_WRAP_T`     | `REPEAT`                 | `0x2901`                 |

> **Note**: The default `TEXTURE_MIN_FILTER` value requires a complete mipmap
> chain for the texture to be considered complete. A newly created texture with
> only a base level image will be incomplete under default parameters.

---

## 2. Texture Completeness (GLES2 Section 3.7.10)

A texture is *complete* when all conditions below are satisfied. Using an
incomplete texture during rendering produces undefined results (effectively
sampling black).

### 2.1 TEXTURE_2D Completeness

Let `w_0` and `h_0` denote the base level (level 0) width and height.

The texture is complete if and only if:

- Level 0 exists and has `w_0 > 0` and `h_0 > 0`.
- If `TEXTURE_MIN_FILTER` is one of the four mipmap modes (`NEAREST_MIPMAP_NEAREST`,
  `LINEAR_MIPMAP_NEAREST`, `NEAREST_MIPMAP_LINEAR`, `LINEAR_MIPMAP_LINEAR`), then
  levels 0 through `q` must all be defined, where:

      q = floor(log2(max(w_0, h_0)))

  Each level `i` (for `1 <= i <= q`) must have dimensions:

      w_i = max(1, floor(w_0 / 2^i))
      h_i = max(1, floor(h_0 / 2^i))

  and the same internal format as the base level.
- If `TEXTURE_MIN_FILTER` is `NEAREST` or `LINEAR`, then only the base level
  needs to be present with valid dimensions.

> **Implementation note**: For non-negative integers, `floor(w / 2^i)` is
> equivalent to `w >> i`. The `max(1, ...)` clamp is essential — without it,
> asymmetric textures (e.g. 256×4) would compute dimension 0 for the smaller
> axis before reaching the final level.

### 2.2 TEXTURE_CUBE_MAP Completeness

A cube map texture is complete if:

1. All six faces are defined at the base level: `POSITIVE_X`, `NEGATIVE_X`,
   `POSITIVE_Y`, `NEGATIVE_Y`, `POSITIVE_Z`, `NEGATIVE_Z`.
2. Every base-level face image is **square** (`width == height`).
3. All six base-level face images have **identical dimensions**.
4. All six base-level face images have the **same internal format**.
5. If a mipmap filter is active, then for **each** face independently, levels
   0 through `q = floor(log2(w_0))` must be defined with:

       s_i = max(1, w_0 >> i)

   Each mip level must have dimensions `s_i × s_i` and match the base level's
   internal format.

---

## 3. WebGL 1.0 NPOT Restrictions (WebGL Section 5.13.8)

Non-Power-Of-Two (NPOT) textures — those whose base level width **or** height
is not a power of two — are subject to additional restrictions in WebGL 1.0:

- `TEXTURE_MIN_FILTER` **must not** use any mipmap filtering mode.
- `TEXTURE_WRAP_S` **must** be `CLAMP_TO_EDGE`.
- `TEXTURE_WRAP_T` **must** be `CLAMP_TO_EDGE`.

A texture violating any of these constraints is incomplete.

> A dimension `d` is a power of two if and only if `d > 0` and `(d & (d-1)) == 0`.

---

## 4. Framebuffer Completeness (GLES2 Section 4.4.5)

A framebuffer object has status `FRAMEBUFFER_COMPLETE` if all the following hold:

### 4.1 Attachment Presence

At least one image must be attached.
→ Otherwise: `FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT`

### 4.2 Attachment Validity (checked BEFORE dimensional consistency)

Each attached image must satisfy:

- **Renderbuffer attachments**:
  - Width and height must be greater than zero.
  - `COLOR_ATTACHMENT0`: internal format must be color-renderable for
    renderbuffers (`RGBA4`, `RGB5_A1`, `RGB565`).
  - `DEPTH_ATTACHMENT`: internal format must be depth-renderable
    (`DEPTH_COMPONENT16`, `DEPTH_STENCIL`).
  - `STENCIL_ATTACHMENT`: internal format must be stencil-renderable
    (`STENCIL_INDEX8`, `DEPTH_STENCIL`).

- **Texture attachments**:
  - The specified mip level must exist in the texture object.
  - Width and height of the attached level must be greater than zero.
  - `COLOR_ATTACHMENT0`: internal format must be color-renderable as a
    texture. Per the WebGL 1.0 specification (Section 6.6), only `RGBA`
    and `RGB` are color-renderable texture formats. `LUMINANCE`,
    `LUMINANCE_ALPHA`, and `ALPHA` are **not** color-renderable.

→ If any attachment fails: `FRAMEBUFFER_INCOMPLETE_ATTACHMENT`

### 4.3 Dimensional Consistency (checked AFTER attachment validity)

All attached images must have identical width and height.
→ Otherwise: `FRAMEBUFFER_INCOMPLETE_DIMENSIONS`

> **Ordering requirement**: If an attachment is both invalid (Section 4.2) and
> dimensionally inconsistent (Section 4.3), the implementation must return
> `FRAMEBUFFER_INCOMPLETE_ATTACHMENT`, not `FRAMEBUFFER_INCOMPLETE_DIMENSIONS`.
> This means attachment validity must be evaluated first.

---

## 5. Draw Call Preconditions (GLES2 Section 2.8 / WebGL Section 5.14)

A call to `drawArrays` or `drawElements` generates an error if any of the
following conditions hold:

| # | Condition                                              | Error Code                       |
|---|--------------------------------------------------------|----------------------------------|
| 1 | No current program object is installed.                | `INVALID_OPERATION`              |
| 2 | The current program has not been successfully linked.  | `INVALID_OPERATION`              |
| 3 | A non-default framebuffer is bound and is not complete.| `INVALID_FRAMEBUFFER_OPERATION`  |
| 4 | An enabled active vertex attribute has no buffer bound.| `INVALID_OPERATION`              |
| 5 | `drawElements` called without an element array buffer. | `INVALID_OPERATION`              |
| 6 | An active sampler's texture unit has no texture bound. | `INVALID_OPERATION`              |
| 7 | An active sampler's bound texture is incomplete.       | `INVALID_OPERATION`              |

> **Note**: An active attribute that is **not** enabled uses a generic constant
> vertex value — this is valid and does not generate an error.

---

## 6. Sampler–Texture Target Compatibility (GLES2 Section 3.7.5)

The GLSL sampler type determines which texture target must be bound:

| Sampler Type   | Required Texture Target   |
|----------------|---------------------------|
| `sampler2D`    | `TEXTURE_2D`              |
| `samplerCube`  | `TEXTURE_CUBE_MAP`        |

Binding a sampler to a texture whose target does not match is a validation error.

---

## 7. GLSL ES Shader Compilation

The reference compiler `glslangValidator` accepts a stage flag via `-S`:

| GLSL Stage | Flag   |
|------------|--------|
| Vertex     | `vert` |
| Fragment   | `frag` |
| Compute    | `comp` |

Error output format for single-file compilation:

    <SEVERITY>: <source_index>:<line_number>: '<token>' : <message>

Where `<source_index>` is always `0` for single-file input and `<line_number>`
is the 1-based line in the source file where the error was detected.
