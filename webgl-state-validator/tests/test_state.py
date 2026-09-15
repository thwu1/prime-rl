"""
Conformance tests for WebGL validation pipeline.

"""
import math
import sys

sys.path.insert(0, "/app")

import pytest

from gl_constants import (
    ALL_CUBE_FACES,
    ALPHA,
    CLAMP_TO_EDGE,
    COLOR_ATTACHMENT0,
    DEPTH_ATTACHMENT,
    DEPTH_COMPONENT16,
    FRAMEBUFFER_COMPLETE,
    FRAMEBUFFER_INCOMPLETE_ATTACHMENT,
    FRAMEBUFFER_INCOMPLETE_DIMENSIONS,
    FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT,
    INVALID_FRAMEBUFFER_OPERATION,
    INVALID_OPERATION,
    LINEAR,
    LINEAR_MIPMAP_LINEAR,
    LINEAR_MIPMAP_NEAREST,
    LUMINANCE,
    LUMINANCE_ALPHA,
    MIRRORED_REPEAT,
    NEAREST,
    NEAREST_MIPMAP_LINEAR,
    NEAREST_MIPMAP_NEAREST,
    NO_ERROR,
    REPEAT,
    RGB,
    RGB5_A1,
    RGB565,
    RGBA,
    RGBA4,
    STENCIL_ATTACHMENT,
    STENCIL_INDEX8,
    TEXTURE_2D,
    TEXTURE_CUBE_MAP,
    TEXTURE_CUBE_MAP_NEGATIVE_X,
    TEXTURE_CUBE_MAP_NEGATIVE_Y,
    TEXTURE_CUBE_MAP_NEGATIVE_Z,
    TEXTURE_CUBE_MAP_POSITIVE_X,
    TEXTURE_CUBE_MAP_POSITIVE_Y,
    TEXTURE_CUBE_MAP_POSITIVE_Z,
)
from state_types import (
    DrawCallState,
    FramebufferAttachment,
    FramebufferState,
    MipLevel,
    ProgramState,
    RenderbufferState,
    TextureState,
)
from validator import WebGLStateValidator


# ─── Fixtures & helpers ─────────────────────────────────────────────────


@pytest.fixture
def v():
    return WebGLStateValidator()


def _tex2d(levels_spec, min_f=NEAREST, mag_f=NEAREST,
           ws=CLAMP_TO_EDGE, wt=CLAMP_TO_EDGE):
    """Build a TEXTURE_2D from a dict {level: (w, h, fmt)} or list [(w,h,fmt), ...]."""
    tex = TextureState(TEXTURE_2D)
    tex.min_filter = min_f
    tex.mag_filter = mag_f
    tex.wrap_s = ws
    tex.wrap_t = wt
    if isinstance(levels_spec, list):
        for i, (w, h, fmt) in enumerate(levels_spec):
            tex.mip_levels[i] = MipLevel(w, h, fmt)
    else:
        for lvl, (w, h, fmt) in levels_spec.items():
            tex.mip_levels[lvl] = MipLevel(w, h, fmt)
    return tex


def _mipchain(bw, bh, fmt=RGBA):
    """Return a complete mipmap chain as [(w, h, fmt), ...]."""
    chain = [(bw, bh, fmt)]
    q = math.floor(math.log2(max(bw, bh)))
    for i in range(1, q + 1):
        chain.append((max(1, bw >> i), max(1, bh >> i), fmt))
    return chain


def _cube(face_levels, min_f=NEAREST, mag_f=NEAREST,
          ws=CLAMP_TO_EDGE, wt=CLAMP_TO_EDGE):
    """Build a TEXTURE_CUBE_MAP.  If *face_levels* keys are ints (levels),
    the same spec is applied to all 6 faces.  Otherwise keys are face constants."""
    tex = TextureState(TEXTURE_CUBE_MAP)
    tex.min_filter = min_f
    tex.mag_filter = mag_f
    tex.wrap_s = ws
    tex.wrap_t = wt
    if all(isinstance(k, int) for k in face_levels):
        for face in ALL_CUBE_FACES:
            tex.cube_faces[face] = {
                lv: MipLevel(w, h, f)
                for lv, (w, h, f) in face_levels.items()
            }
    else:
        for face, levels in face_levels.items():
            tex.cube_faces[face] = {
                lv: MipLevel(w, h, f)
                for lv, (w, h, f) in levels.items()
            }
    return tex


def _rb_att(fmt, w, h):
    return FramebufferAttachment(FramebufferAttachment.RENDERBUFFER,
                                 RenderbufferState(fmt, w, h))


def _tex_att(tex, level=0, face=None):
    return FramebufferAttachment(FramebufferAttachment.TEXTURE,
                                 tex, tex_level=level, tex_face=face)


def _fb(**kw):
    """make_fb(color=att, depth=att, stencil=att)."""
    point_map = {"color": COLOR_ATTACHMENT0,
                 "depth": DEPTH_ATTACHMENT,
                 "stencil": STENCIL_ATTACHMENT}
    fb = FramebufferState()
    for name, att in kw.items():
        fb.attachments[point_map[name]] = att
    return fb


# ═══════════════════════════════════════════════════════════════════════
#  TEXTURE 2D COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════


class TestTexture2D:
    """TEXTURE_2D completeness checks."""

    def test_level0_nearest_complete(self, v):
        tex = _tex2d([(256, 256, RGBA)])
        assert v.is_texture_complete(tex) is True

    def test_no_levels(self, v):
        tex = _tex2d({})
        assert v.is_texture_complete(tex) is False

    def test_zero_width(self, v):
        tex = _tex2d([(0, 64, RGBA)])
        assert v.is_texture_complete(tex) is False

    def test_zero_height(self, v):
        tex = _tex2d([(64, 0, RGBA)])
        assert v.is_texture_complete(tex) is False

    def test_mipmap_filter_no_chain(self, v):
        """Mipmap min-filter but only level 0 => incomplete."""
        tex = _tex2d([(64, 64, RGBA)], min_f=LINEAR_MIPMAP_LINEAR)
        assert v.is_texture_complete(tex) is False

    def test_full_mipmap_64x64(self, v):
        chain = _mipchain(64, 64)          # levels 0..6
        tex = _tex2d(chain, min_f=LINEAR_MIPMAP_LINEAR)
        assert v.is_texture_complete(tex) is True

    def test_missing_intermediate_level(self, v):
        """64x64 chain with level 3 deleted => incomplete."""
        chain = _mipchain(64, 64)
        spec = {i: s for i, s in enumerate(chain)}
        del spec[3]
        tex = _tex2d(spec, min_f=LINEAR_MIPMAP_NEAREST)
        assert v.is_texture_complete(tex) is False

    def test_wrong_mip_dimensions(self, v):
        """16x4 texture: level 2 should be 4x1 not 4x2."""
        tex = _tex2d({
            0: (16, 4, RGBA),
            1: (8, 2, RGBA),
            2: (4, 2, RGBA),      # WRONG — expected 4x1
            3: (2, 1, RGBA),
            4: (1, 1, RGBA),
        }, min_f=NEAREST_MIPMAP_NEAREST)
        assert v.is_texture_complete(tex) is False

    def test_format_mismatch_in_chain(self, v):
        tex = _tex2d({
            0: (4, 4, RGBA),
            1: (2, 2, RGB),       # format mismatch
            2: (1, 1, RGBA),
        }, min_f=LINEAR_MIPMAP_LINEAR)
        assert v.is_texture_complete(tex) is False

    def test_npot_mipmap_rejected(self, v):
        """NPOT + mipmap filter => incomplete (WebGL 1.0 restriction)."""
        tex = _tex2d([(300, 200, RGBA)],
                     min_f=NEAREST_MIPMAP_NEAREST,
                     ws=CLAMP_TO_EDGE, wt=CLAMP_TO_EDGE)
        assert v.is_texture_complete(tex) is False

    def test_npot_repeat_s_rejected(self, v):
        """NPOT + REPEAT on wrap_s => incomplete."""
        tex = _tex2d([(300, 200, RGBA)],
                     min_f=LINEAR,
                     ws=REPEAT, wt=CLAMP_TO_EDGE)
        assert v.is_texture_complete(tex) is False

    def test_npot_mirrored_repeat_t_rejected(self, v):
        """NPOT + MIRRORED_REPEAT on wrap_t => incomplete."""
        tex = _tex2d([(300, 200, RGBA)],
                     min_f=NEAREST,
                     ws=CLAMP_TO_EDGE, wt=MIRRORED_REPEAT)
        assert v.is_texture_complete(tex) is False

    def test_npot_clamp_nearest_ok(self, v):
        """NPOT with NEAREST + CLAMP_TO_EDGE is valid."""
        tex = _tex2d([(300, 200, RGBA)],
                     min_f=NEAREST, mag_f=NEAREST,
                     ws=CLAMP_TO_EDGE, wt=CLAMP_TO_EDGE)
        assert v.is_texture_complete(tex) is True

    def test_rectangular_full_chain(self, v):
        """256x64 POT rectangular texture with correct mip chain (9 levels)."""
        chain = _mipchain(256, 64)
        # Verify expected chain length: floor(log2(256))+1 = 9
        assert len(chain) == 9
        tex = _tex2d(chain, min_f=LINEAR_MIPMAP_LINEAR)
        assert v.is_texture_complete(tex) is True

    def test_1x1_mipmap_ok(self, v):
        """1x1 with mipmap filter — q=0 so only level 0 required."""
        tex = _tex2d([(1, 1, RGBA)], min_f=LINEAR_MIPMAP_LINEAR)
        assert v.is_texture_complete(tex) is True

    def test_default_params_incomplete(self, v):
        """Default WebGL params (mipmap filter + REPEAT) with only level 0
        => incomplete because mip chain is missing."""
        tex = TextureState(TEXTURE_2D)
        tex.mip_levels[0] = MipLevel(64, 64, RGBA)
        assert v.is_texture_complete(tex) is False


# ═══════════════════════════════════════════════════════════════════════
#  TEXTURE CUBE MAP COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════


class TestCubeMap:
    """TEXTURE_CUBE_MAP completeness checks."""

    def test_complete(self, v):
        tex = _cube({0: (64, 64, RGBA)})
        assert v.is_texture_complete(tex) is True

    def test_missing_face(self, v):
        tex = TextureState(TEXTURE_CUBE_MAP)
        tex.min_filter = NEAREST
        tex.wrap_s = CLAMP_TO_EDGE
        tex.wrap_t = CLAMP_TO_EDGE
        for face in ALL_CUBE_FACES[:-1]:           # omit last face
            tex.cube_faces[face] = {0: MipLevel(64, 64, RGBA)}
        assert v.is_texture_complete(tex) is False

    def test_non_square_faces(self, v):
        """Cube map faces must be square."""
        tex = _cube({0: (64, 32, RGBA)})
        assert v.is_texture_complete(tex) is False

    def test_face_size_mismatch(self, v):
        """All faces must share the same dimensions."""
        tex = TextureState(TEXTURE_CUBE_MAP)
        tex.min_filter = NEAREST
        tex.wrap_s = CLAMP_TO_EDGE
        tex.wrap_t = CLAMP_TO_EDGE
        for face in ALL_CUBE_FACES[:5]:
            tex.cube_faces[face] = {0: MipLevel(64, 64, RGBA)}
        tex.cube_faces[ALL_CUBE_FACES[5]] = {0: MipLevel(32, 32, RGBA)}
        assert v.is_texture_complete(tex) is False

    def test_face_format_mismatch(self, v):
        """All faces must share the same internal format."""
        tex = TextureState(TEXTURE_CUBE_MAP)
        tex.min_filter = NEAREST
        tex.wrap_s = CLAMP_TO_EDGE
        tex.wrap_t = CLAMP_TO_EDGE
        for face in ALL_CUBE_FACES[:5]:
            tex.cube_faces[face] = {0: MipLevel(64, 64, RGBA)}
        tex.cube_faces[ALL_CUBE_FACES[5]] = {0: MipLevel(64, 64, RGB)}
        assert v.is_texture_complete(tex) is False

    def test_mipmap_chain_complete(self, v):
        """Full mip chain on all 6 faces of 64x64 cube map."""
        levels = {}
        q = 6  # log2(64)
        for i in range(q + 1):
            s = max(1, 64 >> i)
            levels[i] = (s, s, RGBA)
        tex = _cube(levels, min_f=LINEAR_MIPMAP_LINEAR)
        assert v.is_texture_complete(tex) is True

    def test_mipmap_missing_on_one_face(self, v):
        """One face has a truncated mip chain => incomplete."""
        full = {}
        for i in range(7):
            s = max(1, 64 >> i)
            full[i] = (s, s, RGBA)

        truncated = {0: (64, 64, RGBA), 1: (32, 32, RGBA)}  # levels 2..6 missing

        tex = TextureState(TEXTURE_CUBE_MAP)
        tex.min_filter = LINEAR_MIPMAP_LINEAR
        tex.wrap_s = CLAMP_TO_EDGE
        tex.wrap_t = CLAMP_TO_EDGE
        for face in ALL_CUBE_FACES[:5]:
            tex.cube_faces[face] = {
                lv: MipLevel(w, h, f) for lv, (w, h, f) in full.items()
            }
        tex.cube_faces[ALL_CUBE_FACES[5]] = {
            lv: MipLevel(w, h, f) for lv, (w, h, f) in truncated.items()
        }
        assert v.is_texture_complete(tex) is False


# ═══════════════════════════════════════════════════════════════════════
#  FRAMEBUFFER COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════


class TestFramebuffer:
    """checkFramebufferStatus logic."""

    def test_no_attachments(self, v):
        fb = FramebufferState()
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT

    def test_color_rb_complete(self, v):
        fb = _fb(color=_rb_att(RGBA4, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_rgb565_color_rb_complete(self, v):
        fb = _fb(color=_rb_att(RGB565, 128, 128))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_color_depth_same_size(self, v):
        fb = _fb(color=_rb_att(RGBA4, 256, 256),
                 depth=_rb_att(DEPTH_COMPONENT16, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_color_depth_size_mismatch(self, v):
        fb = _fb(color=_rb_att(RGBA4, 256, 256),
                 depth=_rb_att(DEPTH_COMPONENT16, 128, 128))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_DIMENSIONS

    def test_zero_size_rb(self, v):
        fb = _fb(color=_rb_att(RGBA4, 0, 0))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_depth_format_on_color_point(self, v):
        """DEPTH_COMPONENT16 is not color-renderable."""
        fb = _fb(color=_rb_att(DEPTH_COMPONENT16, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_color_format_on_depth_point(self, v):
        """RGBA4 is not depth-renderable."""
        fb = _fb(color=_rb_att(RGBA4, 256, 256),
                 depth=_rb_att(RGBA4, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_stencil_wrong_format(self, v):
        """RGBA4 is not stencil-renderable."""
        fb = _fb(color=_rb_att(RGBA4, 256, 256),
                 stencil=_rb_att(RGBA4, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_color_depth_stencil_complete(self, v):
        fb = _fb(color=_rb_att(RGB5_A1, 256, 256),
                 depth=_rb_att(DEPTH_COMPONENT16, 256, 256),
                 stencil=_rb_att(STENCIL_INDEX8, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_texture_color_rgba_complete(self, v):
        """RGBA texture on COLOR_ATTACHMENT0 is valid."""
        tex = _tex2d([(256, 256, RGBA)])
        fb = _fb(color=_tex_att(tex))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_texture_color_rgb_complete(self, v):
        """RGB texture on COLOR_ATTACHMENT0 is valid."""
        tex = _tex2d([(128, 128, RGB)])
        fb = _fb(color=_tex_att(tex))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_texture_luminance_not_renderable(self, v):
        """LUMINANCE is not color-renderable for texture attachments."""
        tex = _tex2d([(256, 256, LUMINANCE)])
        fb = _fb(color=_tex_att(tex))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_texture_alpha_not_renderable(self, v):
        """ALPHA is not color-renderable for texture attachments."""
        tex = _tex2d([(256, 256, ALPHA)])
        fb = _fb(color=_tex_att(tex))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_texture_luminance_alpha_not_renderable(self, v):
        """LUMINANCE_ALPHA is not color-renderable for texture attachments."""
        tex = _tex2d([(256, 256, LUMINANCE_ALPHA)])
        fb = _fb(color=_tex_att(tex))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_texture_missing_level(self, v):
        """Texture attached at mip level 3 that does not exist."""
        tex = _tex2d([(256, 256, RGBA)])      # only level 0
        fb = _fb(color=_tex_att(tex, level=3))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_attachment_checked_before_dimensions(self, v):
        """When both attachment-invalid and dimension-mismatch apply,
        INCOMPLETE_ATTACHMENT must be returned (checked first)."""
        fb = FramebufferState()
        # Color: DEPTH_COMPONENT16 is not color-renderable => INCOMPLETE_ATTACHMENT
        fb.attachments[COLOR_ATTACHMENT0] = _rb_att(DEPTH_COMPONENT16, 256, 256)
        # Depth: valid format but different size => would also cause INCOMPLETE_DIMENSIONS
        fb.attachments[DEPTH_ATTACHMENT] = _rb_att(DEPTH_COMPONENT16, 128, 128)
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_INCOMPLETE_ATTACHMENT

    def test_depth_only_complete(self, v):
        """A framebuffer with only a depth attachment is valid."""
        fb = _fb(depth=_rb_att(DEPTH_COMPONENT16, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE

    def test_stencil_only_complete(self, v):
        """A framebuffer with only a stencil attachment is valid."""
        fb = _fb(stencil=_rb_att(STENCIL_INDEX8, 256, 256))
        assert v.check_framebuffer_status(fb) == FRAMEBUFFER_COMPLETE


# ═══════════════════════════════════════════════════════════════════════
#  DRAW CALL VALIDATION
# ═══════════════════════════════════════════════════════════════════════


class TestDrawCall:
    """validate_draw_call checks."""

    @staticmethod
    def _prog(attrs=None, samplers=None):
        p = ProgramState()
        p.active_attributes = attrs if attrs is not None else [0]
        p.samplers = samplers or {}
        return p

    @staticmethod
    def _state(program=None, enabled=None, buffers=None,
               draw_elements=False, elem_buf=False,
               framebuffer=None, tex_units=None):
        s = DrawCallState()
        s.program = program
        if enabled is not None:
            for a in enabled:
                s.attribute_enabled[a] = True
        if buffers is not None:
            for a in buffers:
                s.attribute_buffers[a] = True
        s.is_draw_elements = draw_elements
        s.element_buffer_bound = elem_buf
        s.framebuffer = framebuffer
        s.texture_units = tex_units or {}
        return s

    def test_no_program(self, v):
        s = DrawCallState()
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_unlinked_program(self, v):
        p = self._prog()
        p.linked = False
        s = self._state(program=p, enabled=[0], buffers=[0])
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_incomplete_framebuffer(self, v):
        """Bound FBO with no attachments => INVALID_FRAMEBUFFER_OPERATION."""
        s = self._state(program=self._prog(), enabled=[0], buffers=[0],
                        framebuffer=FramebufferState())
        assert v.validate_draw_call(s) == (False, INVALID_FRAMEBUFFER_OPERATION)

    def test_missing_attribute_buffer(self, v):
        s = self._state(program=self._prog(attrs=[0, 1]),
                        enabled=[0, 1], buffers=[0])    # buffer missing for attr 1
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_valid_draw_arrays(self, v):
        s = self._state(program=self._prog(), enabled=[0], buffers=[0])
        assert v.validate_draw_call(s) == (True, NO_ERROR)

    def test_draw_elements_no_buffer(self, v):
        s = self._state(program=self._prog(), enabled=[0], buffers=[0],
                        draw_elements=True, elem_buf=False)
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_draw_elements_valid(self, v):
        s = self._state(program=self._prog(), enabled=[0], buffers=[0],
                        draw_elements=True, elem_buf=True)
        assert v.validate_draw_call(s) == (True, NO_ERROR)

    def test_incomplete_texture_sampler(self, v):
        """Sampler references a texture that is incomplete => INVALID_OPERATION."""
        bad_tex = TextureState(TEXTURE_2D)         # default params, no levels
        s = self._state(program=self._prog(samplers={0: 0}),
                        enabled=[0], buffers=[0],
                        tex_units={0: bad_tex})
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_complete_texture_sampler(self, v):
        good_tex = _tex2d([(64, 64, RGBA)])
        s = self._state(program=self._prog(samplers={0: 0}),
                        enabled=[0], buffers=[0],
                        tex_units={0: good_tex})
        assert v.validate_draw_call(s) == (True, NO_ERROR)

    def test_unbound_texture_unit(self, v):
        """Sampler references a unit with no texture => INVALID_OPERATION."""
        s = self._state(program=self._prog(samplers={0: 5}),
                        enabled=[0], buffers=[0],
                        tex_units={})
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_disabled_active_attribute_ok(self, v):
        """Active attribute that is *not* enabled uses a generic value — valid."""
        s = DrawCallState()
        s.program = self._prog(attrs=[0, 1])
        s.attribute_enabled[0] = True
        s.attribute_buffers[0] = True
        s.attribute_enabled[1] = False   # uses generic vertex attrib
        assert v.validate_draw_call(s) == (True, NO_ERROR)

    def test_no_active_attributes(self, v):
        """Program with no active attributes — valid (uniforms-only shader)."""
        s = DrawCallState()
        s.program = self._prog(attrs=[])
        assert v.validate_draw_call(s) == (True, NO_ERROR)

    def test_multiple_samplers_one_incomplete(self, v):
        """Two samplers, second one references incomplete texture."""
        good = _tex2d([(32, 32, RGBA)])
        bad = TextureState(TEXTURE_2D)
        s = self._state(program=self._prog(attrs=[0], samplers={0: 0, 1: 1}),
                        enabled=[0], buffers=[0],
                        tex_units={0: good, 1: bad})
        assert v.validate_draw_call(s) == (False, INVALID_OPERATION)

    def test_multiple_samplers_all_complete(self, v):
        good1 = _tex2d([(32, 32, RGBA)])
        good2 = _tex2d([(16, 16, RGB)])
        s = self._state(program=self._prog(attrs=[0], samplers={0: 0, 1: 1}),
                        enabled=[0], buffers=[0],
                        tex_units={0: good1, 1: good2})
        assert v.validate_draw_call(s) == (True, NO_ERROR)


# ═══════════════════════════════════════════════════════════════════════
#  GLSL SHADER ANALYSIS (via glslangValidator)
# ═══════════════════════════════════════════════════════════════════════


class TestShaderAnalyzer:
    """GLSL ES shader compilation and analysis via glslangValidator."""

    @pytest.fixture
    def analyzer(self):
        from shader_analyzer import ShaderAnalyzer
        return ShaderAnalyzer()

    def test_valid_vertex_compiles(self, analyzer):
        """Valid GLSL ES 1.00 vertex shader compiles successfully."""
        source = open("/app/shaders/basic.vert").read()
        ok, errors, warnings = analyzer.compile_shader(source, "vertex")
        assert ok is True
        assert len(errors) == 0

    def test_valid_fragment_compiles(self, analyzer):
        """Valid GLSL ES 1.00 fragment shader compiles successfully."""
        source = open("/app/shaders/basic.frag").read()
        ok, errors, warnings = analyzer.compile_shader(source, "fragment")
        assert ok is True
        assert len(errors) == 0

    def test_multitex_fragment_compiles(self, analyzer):
        """Multi-texture fragment shader with sampler2D and samplerCube compiles."""
        source = open("/app/shaders/multitex.frag").read()
        ok, errors, warnings = analyzer.compile_shader(source, "fragment")
        assert ok is True
        assert len(errors) == 0

    def test_invalid_shader_rejected(self, analyzer):
        """Fragment shader with wrong texture2D arity is rejected."""
        source = open("/app/shaders/invalid.frag").read()
        ok, errors, warnings = analyzer.compile_shader(source, "fragment")
        assert ok is False
        assert len(errors) > 0

    def test_shader_pair_valid(self, analyzer):
        """Valid vertex + fragment shader pair passes pair validation."""
        v_src = open("/app/shaders/basic.vert").read()
        f_src = open("/app/shaders/basic.frag").read()
        both_ok, v_res, f_res = analyzer.validate_shader_pair(v_src, f_src)
        assert both_ok is True
        assert v_res["success"] is True
        assert f_res["success"] is True

    def test_error_line_number(self, analyzer):
        """Error reports contain correct source line numbers."""
        bad_src = (
            "#version 100\n"
            "attribute vec4 a;\n"
            "void main() {\n"
            "  gl_Position = a;\n"
            "  float x = sin();\n"
            "}\n"
        )
        ok, errors, _ = analyzer.compile_shader(bad_src, "vertex")
        assert ok is False
        assert len(errors) > 0
        assert errors[0]["line"] == 5, f"Expected error on line 5, got {errors[0]}"

    def test_version_extraction_es100(self, analyzer):
        """GLSL ES 1.00 version is correctly extracted."""
        version, is_es = analyzer.get_shader_version(
            "#version 100\nvoid main() {}\n"
        )
        assert version == 100
        assert is_es is False  # #version 100 (no 'es' suffix)

    def test_version_extraction_es300(self, analyzer):
        """GLSL ES 3.00 version is correctly extracted."""
        version, is_es = analyzer.get_shader_version(
            "#version 300 es\nvoid main() {}\n"
        )
        assert version == 300
        assert is_es is True


# ═══════════════════════════════════════════════════════════════════════
#  SHADER-STATE CROSS-VALIDATION (conformance database)
# ═══════════════════════════════════════════════════════════════════════


class TestConformanceCheck:
    """Shader-state cross-validation using conformance DB."""

    @pytest.fixture
    def checker(self):
        from conformance_check import ConformanceChecker
        c = ConformanceChecker()
        yield c
        c.close()

    def test_sampler2d_texture2d_compatible(self, checker):
        """sampler2D is compatible with TEXTURE_2D."""
        compat, section = checker.check_sampler_compatibility(
            "sampler2D", TEXTURE_2D
        )
        assert compat is True
        assert section == "GLES2_3.7.5"

    def test_sampler2d_cubemap_incompatible(self, checker):
        """sampler2D is NOT compatible with TEXTURE_CUBE_MAP."""
        compat, section = checker.check_sampler_compatibility(
            "sampler2D", TEXTURE_CUBE_MAP
        )
        assert compat is False

    def test_samplerCube_cubemap_compatible(self, checker):
        """samplerCube is compatible with TEXTURE_CUBE_MAP."""
        compat, section = checker.check_sampler_compatibility(
            "samplerCube", TEXTURE_CUBE_MAP
        )
        assert compat is True
        assert section == "GLES2_3.7.5"

    def test_format_rgba_color_renderable(self, checker):
        """RGBA is color-renderable as a texture attachment."""
        rend, section = checker.check_format_renderable(RGBA, "color_tex")
        assert rend is True

    def test_format_luminance_not_renderable(self, checker):
        """LUMINANCE is not color-renderable as a texture attachment."""
        rend, section = checker.check_format_renderable(LUMINANCE, "color_tex")
        assert rend is False

    def test_program_sampler_validation_correct(self, checker):
        """sampler2D bound to TEXTURE_2D is compatible."""
        samplers = {"u_diffuse": "sampler2D"}
        tex = TextureState(TEXTURE_2D)
        tex.min_filter = NEAREST
        tex.mip_levels[0] = MipLevel(64, 64, RGBA)
        bindings = {"u_diffuse": tex}
        results = checker.validate_program_samplers(samplers, bindings)
        assert len(results) == 1
        assert results[0][1] is True

    def test_program_sampler_wrong_target_rejected(self, checker):
        """samplerCube bound to TEXTURE_2D is rejected."""
        samplers = {"u_envmap": "samplerCube"}
        tex = TextureState(TEXTURE_2D)
        tex.min_filter = NEAREST
        tex.mip_levels[0] = MipLevel(64, 64, RGBA)
        bindings = {"u_envmap": tex}
        results = checker.validate_program_samplers(samplers, bindings)
        assert len(results) == 1
        assert results[0][1] is False
