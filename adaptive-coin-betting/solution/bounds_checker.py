
import ctypes
import os


class BoundsChecker:
    """FFI wrapper for the C adversarial sequence generator and bound functions."""

    def __init__(self):
        lib_path = "/app/lib/libadversary.so"
        if not os.path.exists(lib_path):
            raise FileNotFoundError(
                f"{lib_path} not found. Run 'make -C /app' to build it."
            )
        self._lib = ctypes.CDLL(lib_path)

        self._lib.generate_adversary.argtypes = [
            ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(ctypes.c_double),
        ]
        self._lib.generate_adversary.restype = ctypes.c_int

        self._lib.olo_regret_bound.argtypes = [
            ctypes.c_double, ctypes.c_int, ctypes.c_double,
        ]
        self._lib.olo_regret_bound.restype = ctypes.c_double

        self._lib.adaptive_regret_bound.argtypes = [
            ctypes.c_int, ctypes.c_int,
        ]
        self._lib.adaptive_regret_bound.restype = ctypes.c_double

        self._lib.wealth_lower_bound.argtypes = [ctypes.c_int]
        self._lib.wealth_lower_bound.restype = ctypes.c_double

    def generate_sequence(self, seed, T, dim):
        buf = (ctypes.c_double * (T * dim))()
        ret = self._lib.generate_adversary(seed, T, dim, buf)
        if ret != 0:
            raise RuntimeError("generate_adversary returned non-zero")
        result = []
        for t in range(T):
            row = [buf[t * dim + d] for d in range(dim)]
            result.append(row)
        return result

    def olo_bound(self, competitor, T, lipschitz):
        return self._lib.olo_regret_bound(
            ctypes.c_double(competitor),
            ctypes.c_int(T),
            ctypes.c_double(lipschitz),
        )

    def adaptive_bound(self, interval_len, T):
        return self._lib.adaptive_regret_bound(
            ctypes.c_int(interval_len),
            ctypes.c_int(T),
        )

    def wealth_bound(self, T):
        return self._lib.wealth_lower_bound(ctypes.c_int(T))
