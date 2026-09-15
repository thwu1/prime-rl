"""
WebGL 1.0 State Validation Engine — Reference Implementation

"""
import math

# ─── Constants ───────────────────────────────────────────────────────────

TEXTURE_2D = 0x0DE1
TEXTURE_CUBE_MAP = 0x8513

TEXTURE_CUBE_MAP_POSITIVE_X = 0x8515
TEXTURE_CUBE_MAP_NEGATIVE_X = 0x8516
TEXTURE_CUBE_MAP_POSITIVE_Y = 0x8517
TEXTURE_CUBE_MAP_NEGATIVE_Y = 0x8518
TEXTURE_CUBE_MAP_POSITIVE_Z = 0x8519
TEXTURE_CUBE_MAP_NEGATIVE_Z = 0x851A

ALL_CUBE_FACES = [
    TEXTURE_CUBE_MAP_POSITIVE_X, TEXTURE_CUBE_MAP_NEGATIVE_X,
    TEXTURE_CUBE_MAP_POSITIVE_Y, TEXTURE_CUBE_MAP_NEGATIVE_Y,
    TEXTURE_CUBE_MAP_POSITIVE_Z, TEXTURE_CUBE_MAP_NEGATIVE_Z,
]

NEAREST = 0x2600
LINEAR = 0x2601
NEAREST_MIPMAP_NEAREST = 0x2700
LINEAR_MIPMAP_NEAREST = 0x2701
NEAREST_MIPMAP_LINEAR = 0x2702
LINEAR_MIPMAP_LINEAR = 0x2703

REPEAT = 0x2901
CLAMP_TO_EDGE = 0x812F
MIRRORED_REPEAT = 0x8370

RGBA = 0x1908
RGB = 0x1907
LUMINANCE = 0x1909
LUMINANCE_ALPHA = 0x190A
ALPHA = 0x1906

RGBA4 = 0x8056
RGB5_A1 = 0x8057
RGB565 = 0x8D62
DEPTH_COMPONENT16 = 0x81A5
STENCIL_INDEX8 = 0x8D48
DEPTH_STENCIL = 0x84F9

COLOR_ATTACHMENT0 = 0x8CE0
DEPTH_ATTACHMENT = 0x8D00
STENCIL_ATTACHMENT = 0x8D20
DEPTH_STENCIL_ATTACHMENT = 0x821A

FRAMEBUFFER_COMPLETE = 0x8CD5
FRAMEBUFFER_INCOMPLETE_ATTACHMENT = 0x8CD6
FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT = 0x8CD7
FRAMEBUFFER_INCOMPLETE_DIMENSIONS = 0x8CD9
FRAMEBUFFER_UNSUPPORTED = 0x8CDD

NO_ERROR = 0
INVALID_OPERATION = 0x0502
INVALID_FRAMEBUFFER_OPERATION = 0x0506


# ─── Helpers ─────────────────────────────────────────────────────────────

def _is_power_of_two(n):
    return n > 0 and (n & (n - 1)) == 0


def _requires_mipmaps(min_filter):
    return min_filter in (
        NEAREST_MIPMAP_NEAREST, LINEAR_MIPMAP_NEAREST,
        NEAREST_MIPMAP_LINEAR, LINEAR_MIPMAP_LINEAR,
    )


_COLOR_RENDERABLE_RB = frozenset({RGBA4, RGB5_A1, RGB565})
_COLOR_RENDERABLE_TEX = frozenset({RGBA, RGB})
_DEPTH_RENDERABLE_RB = frozenset({DEPTH_COMPONENT16, DEPTH_STENCIL})
_STENCIL_RENDERABLE_RB = frozenset({STENCIL_INDEX8, DEPTH_STENCIL})


# ─── Data classes ────────────────────────────────────────────────────────

class MipLevel:
    def __init__(self, width, height, internal_format):
        self.width = width
        self.height = height
        self.internal_format = internal_format


class TextureState:
    def __init__(self, target=TEXTURE_2D):
        self.target = target
        self.min_filter = NEAREST_MIPMAP_LINEAR
        self.mag_filter = LINEAR
        self.wrap_s = REPEAT
        self.wrap_t = REPEAT
        self.mip_levels = {}
        self.cube_faces = {}


class RenderbufferState:
    def __init__(self, internal_format, width, height):
        self.internal_format = internal_format
        self.width = width
        self.height = height


class FramebufferAttachment:
    RENDERBUFFER = 'renderbuffer'
    TEXTURE = 'texture'

    def __init__(self, attach_type, obj, tex_level=0, tex_face=None):
        self.attach_type = attach_type
        self.obj = obj
        self.tex_level = tex_level
        self.tex_face = tex_face


class FramebufferState:
    def __init__(self):
        self.attachments = {}


class ProgramState:
    def __init__(self):
        self.linked = True
        self.active_attributes = []
        self.samplers = {}


class DrawCallState:
    def __init__(self):
        self.program = None
        self.attribute_enabled = {}
        self.attribute_buffers = {}
        self.element_buffer_bound = False
        self.framebuffer = None
        self.texture_units = {}
        self.is_draw_elements = False


# ─── Validator ───────────────────────────────────────────────────────────

class WebGLStateValidator:

    # ── texture completeness ─────────────────────────────────────────────

    def is_texture_complete(self, texture):
        if texture.target == TEXTURE_2D:
            return self._check_2d(texture)
        elif texture.target == TEXTURE_CUBE_MAP:
            return self._check_cube(texture)
        return False

    def _check_2d(self, tex):
        levels = tex.mip_levels
        if 0 not in levels:
            return False
        base = levels[0]
        if base.width <= 0 or base.height <= 0:
            return False

        is_pot = _is_power_of_two(base.width) and _is_power_of_two(base.height)
        if not is_pot:
            if _requires_mipmaps(tex.min_filter):
                return False
            if tex.wrap_s != CLAMP_TO_EDGE or tex.wrap_t != CLAMP_TO_EDGE:
                return False

        if _requires_mipmaps(tex.min_filter):
            q = math.floor(math.log2(max(base.width, base.height)))
            for i in range(1, q + 1):
                if i not in levels:
                    return False
                exp_w = max(1, base.width >> i)
                exp_h = max(1, base.height >> i)
                lev = levels[i]
                if lev.width != exp_w or lev.height != exp_h:
                    return False
                if lev.internal_format != base.internal_format:
                    return False

        return True

    def _check_cube(self, tex):
        for face in ALL_CUBE_FACES:
            if face not in tex.cube_faces:
                return False

        ref_face_levels = tex.cube_faces[ALL_CUBE_FACES[0]]
        if 0 not in ref_face_levels:
            return False
        ref_base = ref_face_levels[0]
        if ref_base.width <= 0 or ref_base.height <= 0:
            return False
        if ref_base.width != ref_base.height:
            return False

        is_pot = _is_power_of_two(ref_base.width)
        if not is_pot:
            if _requires_mipmaps(tex.min_filter):
                return False
            if tex.wrap_s != CLAMP_TO_EDGE or tex.wrap_t != CLAMP_TO_EDGE:
                return False

        for face in ALL_CUBE_FACES:
            fl = tex.cube_faces[face]
            if 0 not in fl:
                return False
            fb = fl[0]
            if fb.width != ref_base.width or fb.height != ref_base.height:
                return False
            if fb.internal_format != ref_base.internal_format:
                return False
            if fb.width != fb.height:
                return False

            if _requires_mipmaps(tex.min_filter):
                q = math.floor(math.log2(ref_base.width))
                for i in range(1, q + 1):
                    if i not in fl:
                        return False
                    exp_s = max(1, ref_base.width >> i)
                    lev = fl[i]
                    if lev.width != exp_s or lev.height != exp_s:
                        return False
                    if lev.internal_format != ref_base.internal_format:
                        return False

        return True

    # ── framebuffer completeness ─────────────────────────────────────────

    def _get_attachment_info(self, att):
        """Return (width, height, internal_format) or None."""
        if att.attach_type == FramebufferAttachment.RENDERBUFFER:
            rb = att.obj
            return (rb.width, rb.height, rb.internal_format)
        elif att.attach_type == FramebufferAttachment.TEXTURE:
            tex = att.obj
            if tex.target == TEXTURE_2D:
                if att.tex_level not in tex.mip_levels:
                    return None
                lev = tex.mip_levels[att.tex_level]
                return (lev.width, lev.height, lev.internal_format)
            elif tex.target == TEXTURE_CUBE_MAP:
                if att.tex_face is None or att.tex_face not in tex.cube_faces:
                    return None
                face_levels = tex.cube_faces[att.tex_face]
                if att.tex_level not in face_levels:
                    return None
                lev = face_levels[att.tex_level]
                return (lev.width, lev.height, lev.internal_format)
        return None

    def _is_rb_format_renderable(self, fmt, point):
        if point == COLOR_ATTACHMENT0:
            return fmt in _COLOR_RENDERABLE_RB
        elif point == DEPTH_ATTACHMENT:
            return fmt in _DEPTH_RENDERABLE_RB
        elif point == STENCIL_ATTACHMENT:
            return fmt in _STENCIL_RENDERABLE_RB
        elif point == DEPTH_STENCIL_ATTACHMENT:
            return fmt in (_DEPTH_RENDERABLE_RB & _STENCIL_RENDERABLE_RB)
        return False

    def _is_tex_format_renderable(self, fmt, point):
        if point == COLOR_ATTACHMENT0:
            return fmt in _COLOR_RENDERABLE_TEX
        return False

    def check_framebuffer_status(self, fb):
        if not fb.attachments:
            return FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT

        dims = []
        for point, att in fb.attachments.items():
            info = self._get_attachment_info(att)
            if info is None:
                return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
            w, h, fmt = info
            if w <= 0 or h <= 0:
                return FRAMEBUFFER_INCOMPLETE_ATTACHMENT

            if att.attach_type == FramebufferAttachment.RENDERBUFFER:
                if not self._is_rb_format_renderable(fmt, point):
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT
            elif att.attach_type == FramebufferAttachment.TEXTURE:
                if not self._is_tex_format_renderable(fmt, point):
                    return FRAMEBUFFER_INCOMPLETE_ATTACHMENT

            dims.append((w, h))

        if len(dims) > 1:
            ref = dims[0]
            for d in dims[1:]:
                if d != ref:
                    return FRAMEBUFFER_INCOMPLETE_DIMENSIONS

        return FRAMEBUFFER_COMPLETE

    # ── draw-call validation ─────────────────────────────────────────────

    def validate_draw_call(self, state):
        # 1. program
        if state.program is None or not state.program.linked:
            return (False, INVALID_OPERATION)

        # 2. framebuffer
        if state.framebuffer is not None:
            status = self.check_framebuffer_status(state.framebuffer)
            if status != FRAMEBUFFER_COMPLETE:
                return (False, INVALID_FRAMEBUFFER_OPERATION)

        # 3. vertex attributes
        for attr_loc in state.program.active_attributes:
            if state.attribute_enabled.get(attr_loc, False):
                if not state.attribute_buffers.get(attr_loc, False):
                    return (False, INVALID_OPERATION)

        # 4. element buffer
        if state.is_draw_elements and not state.element_buffer_bound:
            return (False, INVALID_OPERATION)

        # 5. sampler textures
        for _loc, tex_unit in state.program.samplers.items():
            if tex_unit not in state.texture_units:
                return (False, INVALID_OPERATION)
            tex = state.texture_units[tex_unit]
            if not self.is_texture_complete(tex):
                return (False, INVALID_OPERATION)

        return (True, NO_ERROR)
