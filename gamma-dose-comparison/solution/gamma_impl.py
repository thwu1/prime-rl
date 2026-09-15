
"""Gamma index dose comparison library with C-accelerated shell generation."""

import ctypes
import os

import numpy as np
from scipy.interpolate import RegularGridInterpolator

_lib = None


def _load_lib():
    global _lib
    if _lib is None:
        lib_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "accel", "libshell.so"
        )
        _lib = ctypes.CDLL(lib_path)

        _lib.shell_count_2d.argtypes = [ctypes.c_double, ctypes.c_double]
        _lib.shell_count_2d.restype = ctypes.c_int

        _lib.shell_count_3d.argtypes = [ctypes.c_double, ctypes.c_double]
        _lib.shell_count_3d.restype = ctypes.c_int

        _lib.shell_1d.argtypes = [
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
        ]
        _lib.shell_1d.restype = None

        _lib.shell_2d.argtypes = [
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
        ]
        _lib.shell_2d.restype = None

        _lib.shell_3d.argtypes = [
            ctypes.c_double,
            ctypes.c_double,
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_double),
            ctypes.POINTER(ctypes.c_int),
        ]
        _lib.shell_3d.restype = None

    return _lib


def calculate_shell_coordinates(distance, num_dimensions, distance_step_size):
    """Generate uniformly-distributed points on an N-sphere surface.

    Delegates to the C shared library via ctypes.
    Returns a tuple of ``num_dimensions`` coordinate arrays.
    """
    lib = _load_lib()

    if num_dimensions == 1:
        x = (ctypes.c_double * 2)()
        n = ctypes.c_int()
        lib.shell_1d(distance, x, ctypes.byref(n))
        return (np.array(x[: n.value]),)

    elif num_dimensions == 2:
        count = lib.shell_count_2d(distance, distance_step_size)
        x = (ctypes.c_double * count)()
        y = (ctypes.c_double * count)()
        n = ctypes.c_int()
        lib.shell_2d(distance, distance_step_size, x, y, ctypes.byref(n))
        return (np.array(x[: n.value]), np.array(y[: n.value]))

    elif num_dimensions == 3:
        count = lib.shell_count_3d(distance, distance_step_size)
        x = (ctypes.c_double * count)()
        y = (ctypes.c_double * count)()
        z = (ctypes.c_double * count)()
        n = ctypes.c_int()
        lib.shell_3d(
            distance, distance_step_size, x, y, z, ctypes.byref(n)
        )
        return (
            np.array(x[: n.value]),
            np.array(y[: n.value]),
            np.array(z[: n.value]),
        )

    else:
        raise ValueError(f"Unsupported number of dimensions: {num_dimensions}")


def gamma(
    axes_reference,
    dose_reference,
    axes_evaluation,
    dose_evaluation,
    dose_percent_threshold,
    distance_mm_threshold,
    lower_percent_dose_cutoff=20,
    interp_fraction=10,
    max_gamma=None,
    local_gamma=False,
    global_normalisation=None,
):
    """Compute the gamma index between reference and evaluation dose grids."""
    if isinstance(axes_reference, np.ndarray) and axes_reference.ndim == 1:
        axes_reference = (axes_reference,)
    if isinstance(axes_evaluation, np.ndarray) and axes_evaluation.ndim == 1:
        axes_evaluation = (axes_evaluation,)

    axes_reference = tuple(np.asarray(a, dtype=np.float64) for a in axes_reference)
    axes_evaluation = tuple(
        np.asarray(a, dtype=np.float64) for a in axes_evaluation
    )
    dose_reference = np.asarray(dose_reference, dtype=np.float64)
    dose_evaluation = np.asarray(dose_evaluation, dtype=np.float64)

    ndim = len(axes_reference)

    if global_normalisation is None:
        global_normalisation = float(np.max(dose_reference))

    max_gamma_val = max_gamma if max_gamma is not None else np.inf

    lower_cutoff = lower_percent_dose_cutoff / 100.0 * global_normalisation
    dose_threshold_frac = dose_percent_threshold / 100.0
    step_size = distance_mm_threshold / interp_fraction
    max_test_distance = distance_mm_threshold * max_gamma_val

    flat_dose_ref = dose_reference.ravel()
    n_ref = len(flat_dose_ref)

    mesh = np.meshgrid(*axes_reference, indexing="ij")
    flat_mesh = np.array([m.ravel() for m in mesh])

    to_calc = flat_dose_ref >= lower_cutoff
    current_gamma = np.full(n_ref, np.inf)
    still_searching = np.ones(n_ref, dtype=bool)

    interp_func = RegularGridInterpolator(
        axes_evaluation,
        dose_evaluation,
        bounds_error=False,
        fill_value=np.inf,
    )

    distance = 0.0
    while distance <= max_test_distance:
        active = to_calc & still_searching
        if not np.any(active):
            break

        shell = calculate_shell_coordinates(distance, ndim, step_size)
        n_shell = len(shell[0])

        active_coords = flat_mesh[:, active]
        active_dose = flat_dose_ref[active]
        n_active = int(np.sum(active))

        eval_pts = np.zeros((n_shell, n_active, ndim))
        for d in range(ndim):
            eval_pts[:, :, d] = active_coords[d][None, :] + shell[d][:, None]

        eval_doses = interp_func(eval_pts.reshape(-1, ndim)).reshape(
            n_shell, n_active
        )

        if local_gamma:
            with np.errstate(divide="ignore", invalid="ignore"):
                rel_dd = (
                    np.abs(eval_doses - active_dose[None, :])
                    / np.abs(active_dose[None, :])
                )
        else:
            rel_dd = (
                np.abs(eval_doses - active_dose[None, :]) / global_normalisation
            )

        min_rel_dd = np.min(rel_dd, axis=0)

        gamma_d = np.sqrt(
            (min_rel_dd / dose_threshold_frac) ** 2
            + (distance / distance_mm_threshold) ** 2
        )

        current_gamma[active] = np.minimum(current_gamma[active], gamma_d)

        still_searching[active] = current_gamma[active] > (
            distance / distance_mm_threshold
        )

        distance += step_size

    result = current_gamma.reshape(dose_reference.shape)

    if max_gamma is not None:
        with np.errstate(invalid="ignore"):
            result = np.where(result > max_gamma_val, max_gamma_val, result)

    result[np.isinf(result)] = np.nan
    result[dose_reference < lower_cutoff] = np.nan

    return result
