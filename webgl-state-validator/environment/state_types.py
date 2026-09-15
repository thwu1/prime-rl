"""WebGL state object definitions."""

from dataclasses import dataclass, field
from typing import Dict, Optional

from gl_constants import NEAREST, LINEAR, REPEAT


@dataclass
class MipLevel:
    width: int
    height: int
    internal_format: int


@dataclass
class TextureState:
    target: int
    min_filter: int = NEAREST
    mag_filter: int = LINEAR
    wrap_s: int = REPEAT
    wrap_t: int = REPEAT
    mip_levels: Dict[int, MipLevel] = field(default_factory=dict)
    cube_faces: Dict[int, Dict[int, MipLevel]] = field(default_factory=dict)


@dataclass
class RenderbufferState:
    internal_format: int
    width: int
    height: int


@dataclass
class FramebufferAttachment:
    RENDERBUFFER = "renderbuffer"
    TEXTURE = "texture"

    attachment_type: str
    source: object = None
    tex_level: int = 0
    tex_face: Optional[int] = None


@dataclass
class FramebufferState:
    attachments: Dict[int, FramebufferAttachment] = field(default_factory=dict)


@dataclass
class ProgramState:
    linked: bool = True
    active_attributes: list = field(default_factory=list)
    samplers: Dict[int, int] = field(default_factory=dict)


@dataclass
class DrawCallState:
    program: Optional[ProgramState] = None
    attribute_enabled: Dict[int, bool] = field(default_factory=dict)
    attribute_buffers: Dict[int, bool] = field(default_factory=dict)
    is_draw_elements: bool = False
    element_buffer_bound: bool = False
    framebuffer: Optional[FramebufferState] = None
    texture_units: Dict[int, TextureState] = field(default_factory=dict)
