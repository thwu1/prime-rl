
import math


class EulerianFluid:
    """2D Eulerian incompressible fluid simulator using the MAC staggered grid method."""

    def __init__(self, density, num_x, num_y, h):
        self.density = density
        self.numX = num_x + 2
        self.numY = num_y + 2
        self.numCells = self.numX * self.numY
        self.h = h

        self.u = [0.0] * self.numCells
        self.v = [0.0] * self.numCells
        self.newU = [0.0] * self.numCells
        self.newV = [0.0] * self.numCells
        self.p = [0.0] * self.numCells
        self.s = [0.0] * self.numCells
        self.m = [1.0] * self.numCells
        self.newM = [1.0] * self.numCells

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
            self.m[j] = 0.0  # smoke at inlet column i=0

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
                if self.s[i * n + j] != 0.0 and self.s[i * n + j - 1] != 0.0:
                    self.v[i * n + j] += gravity * dt

    def solve_incompressibility(self, num_iters, dt, over_relaxation):
        n = self.numY
        cp = self.density * self.h / dt

        for _ in range(num_iters):
            for i in range(1, self.numX - 1):
                for j in range(1, n - 1):
                    if self.s[i * n + j] == 0.0:
                        continue

                    sx0 = self.s[(i - 1) * n + j]
                    sx1 = self.s[(i + 1) * n + j]
                    sy0 = self.s[i * n + j - 1]
                    sy1 = self.s[i * n + j + 1]
                    s_total = sx0 + sx1 + sy0 + sy1
                    if s_total == 0.0:
                        continue

                    div = (self.u[(i + 1) * n + j] - self.u[i * n + j] +
                           self.v[i * n + j + 1] - self.v[i * n + j])

                    p_corr = -over_relaxation * div / s_total
                    self.p[i * n + j] += cp * p_corr

                    self.u[i * n + j] -= sx0 * p_corr
                    self.u[(i + 1) * n + j] += sx1 * p_corr
                    self.v[i * n + j] -= sy0 * p_corr
                    self.v[i * n + j + 1] += sy1 * p_corr

    def extrapolate(self):
        n = self.numY
        for i in range(self.numX):
            self.u[i * n + 0] = self.u[i * n + 1]
            self.u[i * n + n - 1] = self.u[i * n + n - 2]
        for j in range(n):
            self.v[0 * n + j] = self.v[1 * n + j]
            self.v[(self.numX - 1) * n + j] = self.v[(self.numX - 2) * n + j]

    def sample_field(self, x, y, field_type):
        n = self.numY
        h = self.h
        h1 = 1.0 / h
        h2 = 0.5 * h

        x = max(min(x, self.numX * h), h)
        y = max(min(y, self.numY * h), h)

        dx = 0.0
        dy = 0.0

        if field_type == 'u':
            f = self.u
            dy = h2
        elif field_type == 'v':
            f = self.v
            dx = h2
        elif field_type == 'smoke':
            f = self.m
            dx = h2
            dy = h2
        else:
            return 0.0

        x0 = min(math.floor((x - dx) * h1), self.numX - 1)
        tx = ((x - dx) - x0 * h) * h1
        x1 = min(x0 + 1, self.numX - 1)

        y0 = min(math.floor((y - dy) * h1), self.numY - 1)
        ty = ((y - dy) - y0 * h) * h1
        y1 = min(y0 + 1, self.numY - 1)

        sx = 1.0 - tx
        sy = 1.0 - ty

        val = (sx * sy * f[x0 * n + y0] +
               tx * sy * f[x1 * n + y0] +
               tx * ty * f[x1 * n + y1] +
               sx * ty * f[x0 * n + y1])

        return val

    def _avg_u(self, i, j):
        n = self.numY
        return (self.u[i * n + j - 1] + self.u[i * n + j] +
                self.u[(i + 1) * n + j - 1] + self.u[(i + 1) * n + j]) * 0.25

    def _avg_v(self, i, j):
        n = self.numY
        return (self.v[(i - 1) * n + j] + self.v[i * n + j] +
                self.v[(i - 1) * n + j + 1] + self.v[i * n + j + 1]) * 0.25

    def advect_velocity(self, dt):
        self.newU = list(self.u)
        self.newV = list(self.v)

        n = self.numY
        h = self.h
        h2 = 0.5 * h

        for i in range(1, self.numX):
            for j in range(1, n):
                # u component
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

                # v component
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

        self.u = self.newU
        self.v = self.newV

    def advect_smoke(self, dt):
        self.newM = list(self.m)

        n = self.numY
        h = self.h
        h2 = 0.5 * h

        for i in range(1, self.numX - 1):
            for j in range(1, n - 1):
                if self.s[i * n + j] != 0.0:
                    u_c = (self.u[i * n + j] + self.u[(i + 1) * n + j]) * 0.5
                    v_c = (self.v[i * n + j] + self.v[i * n + j + 1]) * 0.5
                    x = i * h + h2 - dt * u_c
                    y = j * h + h2 - dt * v_c
                    self.newM[i * n + j] = self.sample_field(x, y, 'smoke')

        self.m = self.newM

    def simulate(self, dt, gravity, num_iters, over_relaxation):
        self.integrate(dt, gravity)
        self.p = [0.0] * self.numCells
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
