"""FLIP Fluid Simulator — Python ctypes wrapper around libflip.so"""

import ctypes
import os

FLUID_CELL = 0
AIR_CELL = 1
SOLID_CELL = 2

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libflip.so')
_lib = ctypes.CDLL(_lib_path)

# --- Function prototypes ---

_lib.flip_create.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double,
                              ctypes.c_double, ctypes.c_double, ctypes.c_int]
_lib.flip_create.restype = ctypes.c_void_p

_lib.flip_destroy.argtypes = [ctypes.c_void_p]
_lib.flip_destroy.restype = None

_lib.flip_simulate.argtypes = [ctypes.c_void_p,
                                ctypes.c_double, ctypes.c_double, ctypes.c_double,
                                ctypes.c_int, ctypes.c_int,
                                ctypes.c_double, ctypes.c_int, ctypes.c_int]
_lib.flip_simulate.restype = None

# Scalar getters
for _name, _ret in [('flip_get_num_particles', ctypes.c_int),
                     ('flip_get_fNumX', ctypes.c_int),
                     ('flip_get_fNumY', ctypes.c_int),
                     ('flip_get_fNumCells', ctypes.c_int),
                     ('flip_get_h', ctypes.c_double),
                     ('flip_get_fInvSpacing', ctypes.c_double),
                     ('flip_get_particle_radius', ctypes.c_double),
                     ('flip_get_last_substeps', ctypes.c_int),
                     ('flip_get_last_max_divergence', ctypes.c_double),
                     ('flip_get_last_pressure_iters', ctypes.c_int)]:
    fn = getattr(_lib, _name)
    fn.argtypes = [ctypes.c_void_p]
    fn.restype = _ret

_lib.flip_set_num_particles.argtypes = [ctypes.c_void_p, ctypes.c_int]
_lib.flip_set_num_particles.restype = None

# Array getters (return pointers)
for _name, _ptype in [('flip_get_particle_pos', ctypes.POINTER(ctypes.c_double)),
                       ('flip_get_particle_vel', ctypes.POINTER(ctypes.c_double)),
                       ('flip_get_u', ctypes.POINTER(ctypes.c_double)),
                       ('flip_get_v', ctypes.POINTER(ctypes.c_double)),
                       ('flip_get_s', ctypes.POINTER(ctypes.c_double)),
                       ('flip_get_cell_type', ctypes.POINTER(ctypes.c_int)),
                       ('flip_get_particle_density', ctypes.POINTER(ctypes.c_double))]:
    fn = getattr(_lib, _name)
    fn.argtypes = [ctypes.c_void_p]
    fn.restype = _ptype


class FlipFluid:
    """2D FLIP fluid simulator backed by a C shared library via ctypes."""

    def __init__(self, density, width, height, spacing, particle_radius, max_particles):
        self._handle = _lib.flip_create(density, width, height, spacing,
                                         particle_radius, max_particles)

        # Cache scalar properties (these don't change after construction)
        self.h = _lib.flip_get_h(self._handle)
        self.fNumX = _lib.flip_get_fNumX(self._handle)
        self.fNumY = _lib.flip_get_fNumY(self._handle)
        self.fInvSpacing = _lib.flip_get_fInvSpacing(self._handle)
        self.particleRadius = _lib.flip_get_particle_radius(self._handle)

        # Array attributes — ctypes pointers into C-managed memory
        self.particlePos = _lib.flip_get_particle_pos(self._handle)
        self.particleVel = _lib.flip_get_particle_vel(self._handle)
        self.u = _lib.flip_get_u(self._handle)
        self.v = _lib.flip_get_v(self._handle)
        self.s = _lib.flip_get_s(self._handle)
        self.cellType = _lib.flip_get_cell_type(self._handle)
        self.particleDensity = _lib.flip_get_particle_density(self._handle)

    @property
    def numParticles(self):
        return _lib.flip_get_num_particles(self._handle)

    @numParticles.setter
    def numParticles(self, val):
        _lib.flip_set_num_particles(self._handle, int(val))

    @property
    def lastSubsteps(self):
        return _lib.flip_get_last_substeps(self._handle)

    @property
    def lastMaxDivergence(self):
        return _lib.flip_get_last_max_divergence(self._handle)

    @property
    def lastPressureIters(self):
        return _lib.flip_get_last_pressure_iters(self._handle)

    def simulate(self, dt, gravity, flip_ratio, num_pressure_iters,
                 num_particle_iters, over_relaxation, compensate_drift,
                 separate_particles):
        _lib.flip_simulate(self._handle, dt, gravity, flip_ratio,
                           num_pressure_iters, num_particle_iters,
                           over_relaxation, int(compensate_drift),
                           int(separate_particles))

    def __del__(self):
        try:
            if self._handle:
                _lib.flip_destroy(self._handle)
                self._handle = None
        except Exception:
            pass
