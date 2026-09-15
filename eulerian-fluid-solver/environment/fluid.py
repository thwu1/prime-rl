
import ctypes
import math
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_lib = ctypes.CDLL(os.path.join(_dir, 'libsolver.so'))

_lib.solve_incompressibility.argtypes = [
    ctypes.POINTER(ctypes.c_double),  # u
    ctypes.POINTER(ctypes.c_double),  # v
    ctypes.POINTER(ctypes.c_double),  # p
    ctypes.POINTER(ctypes.c_double),  # s
    ctypes.c_int,                     # numX
    ctypes.c_int,                     # numY
    ctypes.c_double,                  # h
    ctypes.c_double,                  # density
    ctypes.c_double,                  # dt
    ctypes.c_double,                  # over_relaxation
    ctypes.c_double,                  # num_iters
]
_lib.solve_incompressibility.restype = None

_lib.sample_field.argtypes = [
    ctypes.POINTER(ctypes.c_double),  # field
    ctypes.c_int,                     # numX
    ctypes.c_int,                     # numY
    ctypes.c_double,                  # h
    ctypes.c_double,                  # x
    ctypes.c_double,                  # y
    ctypes.c_int,                     # field_type
]
_lib.sample_field.restype = ctypes.c_double


class EulerianFluid:
    """2D grid-based incompressible fluid simulator with C-accelerated solver."""

    def __init__(self, density, num_x, num_y, h):
        self.density = density
        self.numX = num_x + 2
        self.numY = num_y + 2
        self.numCells = self.numX * self.numY
        self.h = h

        ArrayType = ctypes.c_double * self.numCells
        self.u = ArrayType()
        self.v = ArrayType()
        self.newU = ArrayType()
        self.newV = ArrayType()
        self.p = ArrayType()
        self.s = ArrayType()
        self.m = ArrayType()
        self.newM = ArrayType()

        for k in range(self.numCells):
            self.m[k] = 1.0
            self.newM[k] = 1.0

    def setup_wind_tunnel(self, inlet_velocity):
        n = self.numY
        for i in range(self.numX):
            for j in range(n):
                s_val = 1.0
                if i == 0 or j == 0 or j == n - 1:
                    s_val = 0.0
                self.s[i * n + j] = s_val
                if i == 1:
                    self.u[i * n + j] = inlet_velocity

        pipe_h = 0.1 * n
        min_j = int(0.5 * n - 0.5 * pipe_h)
        max_j = int(0.5 * n + 0.5 * pipe_h)
        for j in range(min_j, max_j):
            self.m[j] = 0.0

    def set_obstacle(self, cx, cy, radius):
        n = self.numY
        h = self.h
        r2 = radius * radius
        for i in range(1, self.numX - 1):
            for j in range(1, n - 1):
                dx = (i + 0.5) * h - cx
                dy = (j + 0.5) * h - cy
                if dx * dx + dy * dy < r2:
                    self.s[i * n + j] = 0.0
                    self.m[i * n + j] = 1.0
                    self.u[i * n + j] = 0.0
                    self.u[(i + 1) * n + j] = 0.0
                    self.v[i * n + j] = 0.0
                    self.v[i * n + j + 1] = 0.0

    def integrate(self, dt, gravity):
        n = self.numY
        for i in range(1, self.numX):
            for j in range(1, n - 1):
                if self.s[i * n + j] != 0.0 or self.s[i * n + j - 1] != 0.0:
                    self.v[i * n + j] += gravity * dt

    def solve_incompressibility(self, num_iters, dt, over_relaxation):
        _lib.solve_incompressibility(self.u, self.v, self.p, self.s,
                                      self.numX, self.numY, self.h,
                                      self.density, dt, over_relaxation,
                                      num_iters)

    def extrapolate(self):
        n = self.numY
        for i in range(self.numX):
            self.u[i * n + 0] = self.u[i * n + 1]
            self.u[i * n + n - 1] = self.u[i * n + n - 2]
        for j in range(n):
            self.v[0 * n + j] = self.v[1 * n + j]
            self.v[(self.numX - 1) * n + j] = self.v[(self.numX - 2) * n + j]

    def sample_field(self, x, y, field_type):
        type_map = {'u': 0, 'v': 1, 'smoke': 2}
        ft = type_map.get(field_type, 2)
        if field_type == 'u':
            return _lib.sample_field(self.u, self.numX, self.numY, self.h, x, y, ft)
        elif field_type == 'v':
            return _lib.sample_field(self.v, self.numX, self.numY, self.h, x, y, ft)
        else:
            return _lib.sample_field(self.m, self.numX, self.numY, self.h, x, y, ft)

    def _avg_u(self, i, j):
        n = self.numY
        return (self.u[i * n + j - 1] + self.u[i * n + j] +
                self.u[(i + 1) * n + j - 1] + self.u[(i + 1) * n + j]) * 0.25

    def _avg_v(self, i, j):
        n = self.numY
        return (self.v[(i - 1) * n + j] + self.v[i * n + j] +
                self.v[(i - 1) * n + j + 1] + self.v[i * n + j + 1]) * 0.25

    def advect_velocity(self, dt):
        for k in range(self.numCells):
            self.newU[k] = self.u[k]
            self.newV[k] = self.v[k]

        n = self.numY
        h = self.h
        h2 = 0.5 * h

        for i in range(1, self.numX):
            for j in range(1, n):
                if (self.s[i * n + j] != 0.0 and
                        self.s[(i - 1) * n + j] != 0.0 and
                        j < n - 1):
                    x = i * h
                    y = j * h + h2
                    u_val = self.u[i * n + j]
                    v_val = self._avg_v(i, j)
                    x_bt = x - dt * u_val
                    y_bt = y - dt * v_val
                    self.newU[i * n + j] = self.sample_field(x_bt, y_bt, 'u')

                if (self.s[i * n + j] != 0.0 and
                        self.s[i * n + j - 1] != 0.0 and
                        i < self.numX - 1):
                    x = i * h + h2
                    y = j * h
                    u_val = self._avg_u(i, j)
                    v_val = self.v[i * n + j]
                    x_bt = x - dt * u_val
                    y_bt = y - dt * v_val
                    self.newV[i * n + j] = self.sample_field(x_bt, y_bt, 'v')

        self.u, self.newU = self.newU, self.u
        self.v, self.newV = self.newV, self.v

    def advect_smoke(self, dt):
        pass

    def simulate(self, dt, gravity, num_iters, over_relaxation):
        self.integrate(dt, gravity)
        for k in range(self.numCells):
            self.p[k] = 0.0
        self.solve_incompressibility(num_iters, dt, over_relaxation)
        self.extrapolate()
        self.advect_velocity(dt)
        self.advect_smoke(dt)

    def max_divergence(self):
        n = self.numY
        max_div = 0.0
        for i in range(1, self.numX - 1):
            for j in range(1, n - 1):
                if self.s[i * n + j] == 0.0:
                    continue
                div = (self.u[(i + 1) * n + j] - self.u[i * n + j] +
                       self.v[i * n + j + 1] - self.v[i * n + j])
                if abs(div) > max_div:
                    max_div = abs(div)
        return max_div
