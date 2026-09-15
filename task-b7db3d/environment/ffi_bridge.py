"""Python-C bridge for BRDF kernel functions using ctypes.

Load libbrdf.so and expose typed Python wrappers for all C functions.
The Vec3 struct in C has layout: {double x, double y, double z}.
"""
import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'libbrdf.so')

# TODO: Load the shared library using ctypes.CDLL

# TODO: Define Vec3 as a ctypes.Structure subclass matching the C struct

# TODO: Configure argtypes and restype for each C function:
#   brdf_D_GGX(double NoH, double alpha) -> double
#   brdf_V_SmithGGX(double NoV, double NoL, double alpha) -> double
#   brdf_F_Schlick_scalar(double VoH, double f0) -> double
#   brdf_D_Charlie(double NoH, double roughness) -> double
#   brdf_V_Neubelt(double NoV, double NoL) -> double
#   sample_GGX(double xi_x, double xi_y, double alpha) -> Vec3
#   sample_hemisphere_cosine(double xi_x, double xi_y) -> Vec3
#   sample_hemisphere_uniform(double xi_x, double xi_y) -> Vec3
#   sample_Charlie(double xi_x, double xi_y, double roughness) -> Vec3
#   hammersley_radical_inverse(unsigned int bits) -> double


def D_GGX(NoH, alpha):
    """Call brdf_D_GGX."""
    raise NotImplementedError("Complete the ctypes binding")

def V_SmithGGX(NoV, NoL, alpha):
    """Call brdf_V_SmithGGX."""
    raise NotImplementedError("Complete the ctypes binding")

def F_Schlick(VoH, f0):
    """Call brdf_F_Schlick_scalar."""
    raise NotImplementedError("Complete the ctypes binding")

def D_Charlie(NoH, roughness):
    """Call brdf_D_Charlie."""
    raise NotImplementedError("Complete the ctypes binding")

def V_Neubelt(NoV, NoL):
    """Call brdf_V_Neubelt."""
    raise NotImplementedError("Complete the ctypes binding")

def sample_GGX(xi_x, xi_y, alpha):
    """Call sample_GGX, return (x, y, z) tuple."""
    raise NotImplementedError("Complete the ctypes binding")

def sample_cosine(xi_x, xi_y):
    """Call sample_hemisphere_cosine, return (x, y, z) tuple."""
    raise NotImplementedError("Complete the ctypes binding")

def sample_uniform(xi_x, xi_y):
    """Call sample_hemisphere_uniform, return (x, y, z) tuple."""
    raise NotImplementedError("Complete the ctypes binding")

def sample_charlie(xi_x, xi_y, roughness):
    """Call sample_Charlie, return (x, y, z) tuple."""
    raise NotImplementedError("Complete the ctypes binding")

def hammersley_ri(i):
    """Call hammersley_radical_inverse with unsigned int i."""
    raise NotImplementedError("Complete the ctypes binding")
