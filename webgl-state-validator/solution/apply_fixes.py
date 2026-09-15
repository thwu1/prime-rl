#!/usr/bin/env python3
"""

Implement the WebGL conformance validation engine and fix integration
defects in supporting modules.  Cross-references spec_reference.md
against the codebase, verifies glslangValidator tool behavior, inspects
the conformance database schema, then writes the complete validator
implementation and corrects all supporting modules.
"""

import math
import os
import re
import sqlite3
import subprocess
import tempfile

# ══════════════════════════════════════════════════════════════════════
#  PHASE 1: Derive specification formulas from spec_reference.md
# ══════════════════════════════════════════════════════════════════════

# Mipmap dimension formula: max(1, floor(base / 2^i))
# Equivalent to max(1, base >> i) for non-negative integers.
# The naive formula base // (2**i) gives 0 when base < 2^i.
assert max(1, 64 >> 7) == 1, "64 >> 7 = 0, must clamp to 1"
assert 64 // (2 ** 7) == 0, "Incorrect formula gives 0 (not 1)"
assert max(1, 256 >> 8) == 1, "256 >> 8 = 1"
assert max(1, 4 >> 3) == 1, "4 >> 3 = 0, clamp to 1"
print("[SPEC] Mipmap dimension: max(1, base >> i), not base // (2**i)")

# Mipmap level count: q = floor(log2(max(width, height)))
assert math.floor(math.log2(max(256, 64))) == 8, "256x64 needs 9 levels (0..8)"
assert math.floor(math.log2(max(64, 64))) == 6, "64x64 needs 7 levels (0..6)"
assert math.floor(math.log2(max(1, 1))) == 0, "1x1 needs 1 level (just base)"
print("[SPEC] Level count verified for rectangular and square textures")

# OpenGL ES 2.0 / WebGL 1.0 default texture parameters (Table 3.10):
#   min_filter = NEAREST_MIPMAP_LINEAR (0x2702)
#   mag_filter = LINEAR
#   wrap_s = wrap_t = REPEAT
NEAREST_MIPMAP_LINEAR = 0x2702
NEAREST = 0x2600
assert NEAREST_MIPMAP_LINEAR != NEAREST
print(f"[SPEC] Default min_filter = NEAREST_MIPMAP_LINEAR (0x{NEAREST_MIPMAP_LINEAR:04X})")

# NPOT restrictions: both wrap_s AND wrap_t must be CLAMP_TO_EDGE
CLAMP_TO_EDGE = 0x812F
print("[SPEC] NPOT textures: wrap_s AND wrap_t must be CLAMP_TO_EDGE")

# Color-renderable texture formats (WebGL 1.0 Section 6.6): RGBA and RGB only
RGBA = 0x1908
RGB = 0x1907
LUMINANCE_ALPHA = 0x190A
COLOR_RENDERABLE_TEX = {RGBA, RGB}
assert LUMINANCE_ALPHA not in COLOR_RENDERABLE_TEX
print("[SPEC] Color-renderable tex formats: {RGBA, RGB} — LUMINANCE_ALPHA excluded")

# Framebuffer: attachment validity checked BEFORE dimension consistency
print("[SPEC] FBO check order: attachment validity -> dimension consistency")

# Cube map completeness per GLES2 Section 3.7.10:
# All 6 faces must exist, be square, have same dimensions, same format
# If mipmap filter, each face needs complete mipmap chain
print("[SPEC] Cube map: require square faces, consistent dimensions/format, mipmap chains")

# Draw call: program.linked must be checked; sampled textures must be complete
print("[SPEC] Draw call: check program.linked AND sampler texture completeness")

# ══════════════════════════════════════════════════════════════════════
#  PHASE 2: Empirically verify glslangValidator stage flags and
#           error output format
# ══════════════════════════════════════════════════════════════════════

# Determine valid stage flags from glslangValidator --help
help_result = subprocess.run(
    ["glslangValidator", "--help"], capture_output=True, text=True
)
help_text = help_result.stdout + help_result.stderr

# The fragment shader stage flag is 'frag', not 'comp' (which is compute)
assert "frag" in help_text, "Expected 'frag' in glslangValidator help"
assert "comp" in help_text, "'comp' exists but is for compute shaders"
print("[TOOL] glslangValidator fragment stage: 'frag' (not 'comp')")

# Verify a valid fragment shader compiles with -S frag
with tempfile.NamedTemporaryFile(mode="w", suffix=".frag", delete=False) as f:
    f.write("#version 100\nprecision mediump float;\n"
            "void main() { gl_FragColor = vec4(1.0); }\n")
    tmp_frag = f.name
frag_result = subprocess.run(
    ["glslangValidator", "-S", "frag", tmp_frag],
    capture_output=True, text=True,
)
os.unlink(tmp_frag)
assert frag_result.returncode == 0, "Valid frag shader must compile with -S frag"
print("[TOOL] Verified: -S frag compiles valid fragment shaders")

# Verify error output format: ERROR: <source_idx>:<line_num>: '<token>' : <msg>
# source_idx is always 0 for single-file compilation.
with tempfile.NamedTemporaryFile(mode="w", suffix=".vert", delete=False) as f:
    f.write("#version 100\nattribute vec4 a;\nvoid main() {\n"
            "  gl_Position = a;\n  float x = sin();\n}\n")
    tmp_vert = f.name
err_result = subprocess.run(
    ["glslangValidator", "-S", "vert", tmp_vert],
    capture_output=True, text=True,
)
os.unlink(tmp_vert)
err_text = err_result.stdout + err_result.stderr

# Parse the error format to determine which regex group is the line number
found_error = False
for line in err_text.splitlines():
    m = re.match(r"^ERROR:\s+(\d+):(\d+):", line)
    if m:
        source_idx = int(m.group(1))
        line_num = int(m.group(2))
        assert source_idx == 0, "Source index should be 0"
        assert line_num == 5, f"Error should be on line 5, got {line_num}"
        found_error = True
        break
assert found_error, "Should have found an ERROR line"
print("[TOOL] Error format: ERROR: <source_idx>:<line_num>: ...")
print("[TOOL] In 5-group regex: group(2)=source_idx, group(3)=line_num")

# ══════════════════════════════════════════════════════════════════════
#  PHASE 3: Inspect conformance database schema
# ══════════════════════════════════════════════════════════════════════

conn = sqlite3.connect("/app/conformance.db")

# Check the actual column names in format_compatibility
schema_row = conn.execute(
    "SELECT sql FROM sqlite_master WHERE name='format_compatibility'"
).fetchone()
schema_sql = schema_row[0]
assert "texture_target" in schema_sql, "Column is 'texture_target'"
assert "texture_format" not in schema_sql, "'texture_format' does not exist"
print(f"[DB] format_compatibility schema: {schema_sql}")
print("[DB] Correct column name: 'texture_target' (not 'texture_format')")

# Verify sampler-target compatibility data
TEXTURE_2D = 0x0DE1
TEXTURE_CUBE_MAP = 0x8513
compat_rows = conn.execute(
    "SELECT sampler_type, texture_target, compatible "
    "FROM format_compatibility WHERE compatible = 1"
).fetchall()
sampler_map = {}
for s_type, target, _ in compat_rows:
    sampler_map[s_type] = target
assert sampler_map["sampler2D"] == TEXTURE_2D, "sampler2D -> TEXTURE_2D"
assert sampler_map["samplerCube"] == TEXTURE_CUBE_MAP, "samplerCube -> TEXTURE_CUBE_MAP"
conn.close()
print(f"[DB] sampler2D -> TEXTURE_2D (0x{TEXTURE_2D:04X})")
print(f"[DB] samplerCube -> TEXTURE_CUBE_MAP (0x{TEXTURE_CUBE_MAP:04X})")

# ══════════════════════════════════════════════════════════════════════
#  PHASE 4: Implement the validation engine and fix supporting modules
# ══════════════════════════════════════════════════════════════════════

print("\n=== Implementing validation engine and fixing modules ===\n")

# ── Fix state_types.py: default min_filter must be NEAREST_MIPMAP_LINEAR ──
code = open("/app/state_types.py").read()
code = code.replace(
    "from gl_constants import NEAREST, LINEAR, REPEAT",
    "from gl_constants import NEAREST_MIPMAP_LINEAR, LINEAR, REPEAT",
)
code = code.replace(
    "min_filter: int = NEAREST",
    "min_filter: int = NEAREST_MIPMAP_LINEAR",
)
with open("/app/state_types.py", "w") as f:
    f.write(code)
print("Fixed state_types.py: default min_filter -> NEAREST_MIPMAP_LINEAR")

# ── Implement the complete validator.py from specification ──────────
VALIDATOR_IMPL = '''\
"""WebGL 1.0 state validation engine."""

import math
from gl_constants import *
from state_types import FramebufferAttachment


class WebGLStateValidator:
    """Validates WebGL state machine behavior for conformance testing."""

    def is_texture_complete(self, texture):
        """Check whether a texture object is complete for sampling."""
        if texture.target == TEXTURE_2D:
            return self._check_2d_complete(texture)
        elif texture.target == TEXTURE_CUBE_MAP:
            return self._check_cubemap_complete(texture)
        return False

    @staticmethod
    def _is_npot(w, h):
        """Return True if either dimension is not a power of two."""
        return (w & (w - 1)) != 0 or (h & (h - 1)) != 0

    def _check_2d_complete(self, tex):
        # Base level must exist with positive dimensions
        if 0 not in tex.mip_levels:
            return False
        base = tex.mip_levels[0]
        if base.width <= 0 or base.height <= 0:
            return False

        # WebGL 1.0 NPOT texture restrictions
        if self._is_npot(base.width, base.height):
            if tex.min_filter in MIPMAP_FILTERS:
                return False
            if tex.wrap_s != CLAMP_TO_EDGE or tex.wrap_t != CLAMP_TO_EDGE:
                return False

        # Non-mipmap filters only require the base level
        if tex.min_filter not in MIPMAP_FILTERS:
            return True

        # Validate the full mipmap chain
        q = int(math.log2(max(base.width, base.height)))
        for i in range(1, q + 1):
            if i not in tex.mip_levels:
                return False
            level = tex.mip_levels[i]
            expected_w = max(1, base.width >> i)
            expected_h = max(1, base.height >> i)
            if level.width != expected_w or level.height != expected_h:
                return False
            if level.internal_format != base.internal_format:
                return False
        return True

    def _check_cubemap_complete(self, tex):
        # All six faces must have a base level
        for face in ALL_CUBE_FACES:
            if face not in tex.cube_faces:
                return False
            if 0 not in tex.cube_faces[face]:
                return False

        # All faces must be square, same dimensions, and same format
        ref = tex.cube_faces[ALL_CUBE_FACES[0]][0]
        if ref.width != ref.height:
            return False
        for face in ALL_CUBE_FACES[1:]:
            level = tex.cube_faces[face][0]
            if level.width != level.height:
                return False
            if level.width != ref.width:
                return False
            if level.internal_format != ref.internal_format:
                return False

        # Mipmap chain validation on each face
        if tex.min_filter in MIPMAP_FILTERS:
            for face in ALL_CUBE_FACES:
                base = tex.cube_faces[face][0]
                q = int(math.log2(base.width))
                for i in range(1, q + 1):
                    if i not in tex.cube_faces[face]:
                        return False
                    s = max(1, base.width >> i)
                    level = tex.cube_faces[face][i]
                    if level.width != s or level.height != s:
                        return False
                    if level.internal_format != base.internal_format:
                        return False
        return True

    @staticmethod
    def _color_renderable_rb(fmt):
        """Color-renderable formats for renderbuffer attachments."""
        return fmt in {RGBA4, RGB5_A1, RGB565}

    @staticmethod
    def _color_renderable_tex(fmt):
        """Color-renderable formats for texture attachments."""
        return fmt in {RGBA, RGB}

    @staticmethod
    def _depth_renderable(fmt):
        """Depth-renderable formats."""
        return fmt in {DEPTH_COMPONENT16, DEPTH_STENCIL}

    @staticmethod
    def _stencil_renderable(fmt):
        """Stencil-renderable formats."""
        return fmt in {STENCIL_INDEX8, DEPTH_STENCIL}

    def check_framebuffer_status(self, fb):
        """Return the framebuffer completeness status constant."""
        if not fb.attachments:
            return FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT

        # Validate each attachment first (format, dimensions, existence)
        for point, att in fb.attachments.items():
            if att.attachment_type == FramebufferAttachment.RENDERBUFFER:
                rb = att.source
                if rb.width == 0 or rb.height == 0:
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
                if point == COLOR_ATTACHMENT0 and not self._color_renderable_rb(rb.internal_format):
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
                elif point == DEPTH_ATTACHMENT and not self._depth_renderable(rb.internal_format):
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
                elif point == STENCIL_ATTACHMENT and not self._stencil_renderable(rb.internal_format):
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
            elif att.attachment_type == FramebufferAttachment.TEXTURE:
                tex = att.source
                if att.tex_level not in tex.mip_levels:
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
                lvl = tex.mip_levels[att.tex_level]
                if lvl.width == 0 or lvl.height == 0:
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
                if point == COLOR_ATTACHMENT0 and not self._color_renderable_tex(lvl.internal_format):
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT

        # Then check dimensional consistency across all attachments
        sizes = set()
        for point, att in fb.attachments.items():
            if att.attachment_type == FramebufferAttachment.RENDERBUFFER:
                rb = att.source
                sizes.add((rb.width, rb.height))
            elif att.attachment_type == FramebufferAttachment.TEXTURE:
                tex = att.source
                if att.tex_level in tex.mip_levels:
                    lvl = tex.mip_levels[att.tex_level]
                    sizes.add((lvl.width, lvl.height))
        if len(sizes) > 1:
            return FRAMEBUFFER_INCOMPLETE_DIMENSIONS

        return FRAMEBUFFER_COMPLETE

    def validate_draw_call(self, state):
        """Validate all draw-call preconditions. Returns (ok, error_code)."""
        # Program must be present and linked
        if state.program is None:
            return (False, INVALID_OPERATION)

        if not state.program.linked:
            return (False, INVALID_OPERATION)

        # Framebuffer completeness
        if state.framebuffer is not None:
            status = self.check_framebuffer_status(state.framebuffer)
            if status != FRAMEBUFFER_COMPLETE:
                return (False, INVALID_FRAMEBUFFER_OPERATION)

        # Enabled active attributes must have buffer bindings
        for attr in state.program.active_attributes:
            if state.attribute_enabled.get(attr, False):
                if not state.attribute_buffers.get(attr, False):
                    return (False, INVALID_OPERATION)

        # Element array buffer required for drawElements
        if state.is_draw_elements and not state.element_buffer_bound:
            return (False, INVALID_OPERATION)

        # Active samplers must reference bound AND complete textures
        for sampler_loc, tex_unit in state.program.samplers.items():
            if tex_unit not in state.texture_units:
                return (False, INVALID_OPERATION)
            if not self.is_texture_complete(state.texture_units[tex_unit]):
                return (False, INVALID_OPERATION)

        return (True, NO_ERROR)
'''

with open("/app/validator.py", "w") as f:
    f.write(VALIDATOR_IMPL)
print("Implemented validator.py: texture completeness, framebuffer status, draw-call validation")

# ── Fix shader_analyzer.py ──────────────────────────────────────────
# Defect 1: Fragment stage mapped to "comp" (compute) instead of "frag"
# Defect 2: Error line extraction uses m.group(2) (source index) not m.group(3) (line)
code = open("/app/shader_analyzer.py").read()
code = code.replace('"fragment": "comp"', '"fragment": "frag"')
code = code.replace("int(m.group(2))", "int(m.group(3))")
with open("/app/shader_analyzer.py", "w") as f:
    f.write(code)
print("Fixed shader_analyzer.py: fragment stage 'comp' -> 'frag',")
print("  error line parsing group(2) -> group(3)")

# ── Fix conformance_check.py ───────────────────────────────────────
# Defect 1: SQL column name 'texture_format' should be 'texture_target'
# Defect 2: sampler type -> target mapping is inverted
code = open("/app/conformance_check.py").read()
code = code.replace("texture_format", "texture_target")
code = code.replace('"sampler2D": TEXTURE_CUBE_MAP', '"sampler2D": TEXTURE_2D')
code = code.replace('"samplerCube": TEXTURE_2D', '"samplerCube": TEXTURE_CUBE_MAP')
with open("/app/conformance_check.py", "w") as f:
    f.write(code)
print("Fixed conformance_check.py: SQL column name, sampler type mapping")

print("\nAll implementation and fixes applied successfully.")
