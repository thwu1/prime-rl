"""Python ctypes bindings for libsdf.so — SDF primitive evaluation."""
import ctypes
import os

_lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libsdf.so")
_lib = ctypes.CDLL(_lib_path)

_lib.sd_sphere.argtypes = [ctypes.c_double] * 4
_lib.sd_sphere.restype = ctypes.c_double

_lib.sd_torus.argtypes = [ctypes.c_double] * 5
_lib.sd_torus.restype = ctypes.c_double

_lib.sd_round_box.argtypes = [ctypes.c_double] * 7
_lib.sd_round_box.restype = ctypes.c_double

_lib.sd_octahedron.argtypes = [ctypes.c_double] * 4
_lib.sd_octahedron.restype = ctypes.c_double

_lib.smin_poly.argtypes = [ctypes.c_double] * 3
_lib.smin_poly.restype = ctypes.c_double


def sd_sphere(px, py, pz, r):
    return _lib.sd_sphere(px, py, pz, r)


def sd_torus(px, py, pz, R, r):
    return _lib.sd_torus(px, py, pz, R, r)


def sd_round_box(px, py, pz, bx, by, bz, rad):
    return _lib.sd_round_box(px, py, pz, bx, by, bz, rad)


def sd_octahedron(px, py, pz, s):
    return _lib.sd_octahedron(px, py, pz, s)


def smin_poly(d1, d2, k):
    return _lib.smin_poly(d1, d2, k)
