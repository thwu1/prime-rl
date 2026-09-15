"""
WebGL 1.0 State Validation Engine

Implements texture completeness, framebuffer completeness, and draw call
validation according to the OpenGL ES 2.0 and WebGL 1.0 specifications.

"""
import math

# ─── Constants ───────────────────────────────────────────────────────────

# Texture targets
TEXTURE_2D = 0x0DE1
TEXTURE_CUBE_MAP = 0x8513

# Cube map face targets
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

# Texture minification filters
NEAREST = 0x2600
LINEAR = 0x2601
NEAREST_MIPMAP_NEAREST = 0x2700
LINEAR_MIPMAP_NEAREST = 0x2701
NEAREST_MIPMAP_LINEAR = 0x2702
LINEAR_MIPMAP_LINEAR = 0x2703

# Texture wrap modes
REPEAT = 0x2901
CLAMP_TO_EDGE = 0x812F
MIRRORED_REPEAT = 0x8370

# Texture internal formats
RGBA = 0x1908
RGB = 0x1907
LUMINANCE = 0x1909
LUMINANCE_ALPHA = 0x190A
ALPHA = 0x1906

# Renderbuffer internal formats
RGBA4 = 0x8056
RGB5_A1 = 0x8057
RGB565 = 0x8D62
DEPTH_COMPONENT16 = 0x81A5
STENCIL_INDEX8 = 0x8D48
DEPTH_STENCIL = 0x84F9

# Framebuffer attachment points
COLOR_ATTACHMENT0 = 0x8CE0
DEPTH_ATTACHMENT = 0x8D00
STENCIL_ATTACHMENT = 0x8D20
DEPTH_STENCIL_ATTACHMENT = 0x821A

# Framebuffer completeness status codes
FRAMEBUFFER_COMPLETE = 0x8CD5
FRAMEBUFFER_INCOMPLETE_ATTACHMENT = 0x8CD6
FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT = 0x8CD7
FRAMEBUFFER_INCOMPLETE_DIMENSIONS = 0x8CD9
FRAMEBUFFER_UNSUPPORTED = 0x8CDD

# GL error codes
NO_ERROR = 0
INVALID_OPERATION = 0x0502
INVALID_FRAMEBUFFER_OPERATION = 0x0506


# ─── Data classes ────────────────────────────────────────────────────────

class MipLevel:
    """A single mipmap level image."""
    def __init__(self, width: int, height: int, internal_format: int):
        self.width = width
        self.height = height
        self.internal_format = internal_format


class TextureState:
    """
    Full state of a WebGL texture object.

    For TEXTURE_2D: populate ``mip_levels`` — dict mapping level (int) to MipLevel.
    For TEXTURE_CUBE_MAP: populate ``cube_faces`` — dict mapping face constant
    (e.g. TEXTURE_CUBE_MAP_POSITIVE_X) to {level: MipLevel}.

    Default filter and wrap parameters match WebGL defaults:
      min_filter = NEAREST_MIPMAP_LINEAR
      mag_filter = LINEAR
      wrap_s = REPEAT
      wrap_t = REPEAT
    """
    def __init__(self, target: int = TEXTURE_2D):
        self.target = target
        self.min_filter = NEAREST_MIPMAP_LINEAR
        self.mag_filter = LINEAR
        self.wrap_s = REPEAT
        self.wrap_t = REPEAT
        self.mip_levels: dict[int, MipLevel] = {}
        self.cube_faces: dict[int, dict[int, MipLevel]] = {}


class RenderbufferState:
    """A WebGL renderbuffer object."""
    def __init__(self, internal_format: int, width: int, height: int):
        self.internal_format = internal_format
        self.width = width
        self.height = height


class FramebufferAttachment:
    """An attachment to a framebuffer — either a renderbuffer or a texture level."""
    RENDERBUFFER = 'renderbuffer'
    TEXTURE = 'texture'

    def __init__(self, attach_type: str, obj, tex_level: int = 0,
                 tex_face: int | None = None):
        self.attach_type = attach_type   # RENDERBUFFER or TEXTURE
        self.obj = obj                   # RenderbufferState or TextureState
        self.tex_level = tex_level       # mip level (texture attachments only)
        self.tex_face = tex_face         # cube face (cube map textures only)


class FramebufferState:
    """A WebGL framebuffer object."""
    def __init__(self):
        self.attachments: dict[int, FramebufferAttachment] = {}


class ProgramState:
    """A linked WebGL shader program."""
    def __init__(self):
        self.linked: bool = True
        self.active_attributes: list[int] = []        # attribute locations used
        self.samplers: dict[int, int] = {}             # location -> texture unit


class DrawCallState:
    """WebGL state snapshot relevant to draw-call validation."""
    def __init__(self):
        self.program: ProgramState | None = None
        self.attribute_enabled: dict[int, bool] = {}   # location -> enabled?
        self.attribute_buffers: dict[int, bool] = {}   # location -> buffer bound?
        self.element_buffer_bound: bool = False
        self.framebuffer: FramebufferState | None = None   # None = default FBO
        self.texture_units: dict[int, TextureState] = {}   # unit -> texture
        self.is_draw_elements: bool = False


# ─── Validator ───────────────────────────────────────────────────────────

class WebGLStateValidator:
    """
    Validates WebGL 1.0 state. Implement every method below.
    """

    def is_texture_complete(self, texture: TextureState) -> bool:
        """
        Determine whether *texture* is complete for sampling.

        Rules (OpenGL ES 2.0 §3.7.10 + WebGL 1.0 §6.2):
        - TEXTURE_2D: base level must exist with positive dimensions; if a
          mipmap filter is active, every level from 0..q must be present with
          correct floor-divided dimensions and matching format.
        - TEXTURE_CUBE_MAP: all 6 faces must be present, square, same size and
          format; mipmap chain rules apply per-face.
        - WebGL NPOT restriction: if either dimension is not a power of two,
          mipmap filtering is forbidden and wrap modes must be CLAMP_TO_EDGE.
        """
        raise NotImplementedError()

    def check_framebuffer_status(self, fb: FramebufferState) -> int:
        """
        Return a framebuffer completeness status constant.

        Check order: missing -> attachment -> dimensions -> complete.

        - INCOMPLETE_MISSING_ATTACHMENT: no images attached.
        - INCOMPLETE_ATTACHMENT: any attached image has zero size, or the
          format is not renderable for that attachment point.
          Color-renderable RB formats: RGBA4, RGB5_A1, RGB565.
          Color-renderable texture formats: RGBA, RGB.
          Depth-renderable RB formats: DEPTH_COMPONENT16, DEPTH_STENCIL.
          Stencil-renderable RB formats: STENCIL_INDEX8, DEPTH_STENCIL.
          No texture format is depth- or stencil-renderable in base WebGL 1.0.
        - INCOMPLETE_DIMENSIONS: attached images differ in width or height.
        - FRAMEBUFFER_COMPLETE otherwise.

        For texture attachments, the dimensions and format of the *specific
        mip level* that is attached apply.  If the level does not exist in
        the texture, the attachment is incomplete.
        """
        raise NotImplementedError()

    def validate_draw_call(self, state: DrawCallState) -> tuple[bool, int]:
        """
        Return ``(is_valid, error_code)``.

        Check order:
        1. Program must be bound and linked         -> INVALID_OPERATION
        2. Bound FBO (if any) must be complete       -> INVALID_FRAMEBUFFER_OPERATION
        3. Every *enabled* attribute that the program uses must have a buffer
                                                     -> INVALID_OPERATION
        4. drawElements requires an element buffer   -> INVALID_OPERATION
        5. Every sampler must reference a texture unit whose texture is
           complete (WebGL-specific rule)             -> INVALID_OPERATION

        Return ``(True, NO_ERROR)`` when all checks pass.
        """
        raise NotImplementedError()
