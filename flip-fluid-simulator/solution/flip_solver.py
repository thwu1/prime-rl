"""FLIP Fluid Simulator — Complete Solution."""

import math

FLUID_CELL = 0
AIR_CELL = 1
SOLID_CELL = 2


def clamp(x, min_val, max_val):
    if x < min_val:
        return min_val
    elif x > max_val:
        return max_val
    return x


class FlipFluid:
    """2D FLIP (Fluid-Implicit-Particle) fluid simulator on a MAC staggered grid."""

    def __init__(self, density, width, height, spacing, particle_radius, max_particles):
        self.density = density
        self.fNumX = int(width / spacing) + 1
        self.fNumY = int(height / spacing) + 1
        self.h = max(width / self.fNumX, height / self.fNumY)
        self.fInvSpacing = 1.0 / self.h
        self.fNumCells = self.fNumX * self.fNumY

        self.u = [0.0] * self.fNumCells
        self.v = [0.0] * self.fNumCells
        self.du = [0.0] * self.fNumCells
        self.dv = [0.0] * self.fNumCells
        self.prevU = [0.0] * self.fNumCells
        self.prevV = [0.0] * self.fNumCells
        self.p = [0.0] * self.fNumCells
        self.s = [0.0] * self.fNumCells
        self.cellType = [0] * self.fNumCells
        self.particleDensity = [0.0] * self.fNumCells

        self.maxParticles = max_particles
        self.particlePos = [0.0] * (2 * max_particles)
        self.particleVel = [0.0] * (2 * max_particles)
        self.numParticles = 0
        self.particleRadius = particle_radius
        self.particleRestDensity = 0.0

        self.pInvSpacing = 1.0 / (2.2 * particle_radius)
        self.pNumX = int(width * self.pInvSpacing) + 1
        self.pNumY = int(height * self.pInvSpacing) + 1
        self.pNumCells = self.pNumX * self.pNumY
        self.numCellParticles = [0] * self.pNumCells
        self.firstCellParticle = [0] * (self.pNumCells + 1)
        self.cellParticleIds = [0] * max_particles

    def integrate_particles(self, dt, gravity):
        for i in range(self.numParticles):
            self.particleVel[2 * i + 1] += dt * gravity
            self.particlePos[2 * i] += self.particleVel[2 * i] * dt
            self.particlePos[2 * i + 1] += self.particleVel[2 * i + 1] * dt

    def push_particles_apart(self, num_iters):
        # Count particles per hash cell
        for i in range(self.pNumCells):
            self.numCellParticles[i] = 0

        for i in range(self.numParticles):
            x = self.particlePos[2 * i]
            y = self.particlePos[2 * i + 1]
            xi = clamp(int(x * self.pInvSpacing), 0, self.pNumX - 1)
            yi = clamp(int(y * self.pInvSpacing), 0, self.pNumY - 1)
            cell_nr = xi * self.pNumY + yi
            self.numCellParticles[cell_nr] += 1

        # Build prefix sum (reverse)
        first = 0
        for i in range(self.pNumCells):
            first += self.numCellParticles[i]
            self.firstCellParticle[i] = first
        self.firstCellParticle[self.pNumCells] = first

        # Assign particle ids to cells
        for i in range(self.numParticles):
            x = self.particlePos[2 * i]
            y = self.particlePos[2 * i + 1]
            xi = clamp(int(x * self.pInvSpacing), 0, self.pNumX - 1)
            yi = clamp(int(y * self.pInvSpacing), 0, self.pNumY - 1)
            cell_nr = xi * self.pNumY + yi
            self.firstCellParticle[cell_nr] -= 1
            self.cellParticleIds[self.firstCellParticle[cell_nr]] = i

        # Push overlapping particles apart
        min_dist = 2.0 * self.particleRadius
        min_dist2 = min_dist * min_dist

        for _it in range(num_iters):
            for i in range(self.numParticles):
                px = self.particlePos[2 * i]
                py = self.particlePos[2 * i + 1]

                pxi = int(px * self.pInvSpacing)
                pyi = int(py * self.pInvSpacing)
                x0 = max(pxi - 1, 0)
                y0 = max(pyi - 1, 0)
                x1 = min(pxi + 1, self.pNumX - 1)
                y1 = min(pyi + 1, self.pNumY - 1)

                for xi in range(x0, x1 + 1):
                    for yi in range(y0, y1 + 1):
                        cell_nr = xi * self.pNumY + yi
                        fp = self.firstCellParticle[cell_nr]
                        lp = self.firstCellParticle[cell_nr + 1]
                        for j in range(fp, lp):
                            pid = self.cellParticleIds[j]
                            if pid == i:
                                continue
                            qx = self.particlePos[2 * pid]
                            qy = self.particlePos[2 * pid + 1]
                            ddx = qx - px
                            ddy = qy - py
                            d2 = ddx * ddx + ddy * ddy
                            if d2 > min_dist2 or d2 == 0.0:
                                continue
                            d = math.sqrt(d2)
                            s = 0.5 * (min_dist - d) / d
                            ddx *= s
                            ddy *= s
                            self.particlePos[2 * i] -= ddx
                            self.particlePos[2 * i + 1] -= ddy
                            self.particlePos[2 * pid] += ddx
                            self.particlePos[2 * pid + 1] += ddy

    def handle_collisions(self):
        h = 1.0 / self.fInvSpacing
        r = self.particleRadius
        min_x = h + r
        max_x = (self.fNumX - 1) * h - r
        min_y = h + r
        max_y = (self.fNumY - 1) * h - r

        for i in range(self.numParticles):
            x = self.particlePos[2 * i]
            y = self.particlePos[2 * i + 1]

            if x < min_x:
                x = min_x
                self.particleVel[2 * i] = 0.0
            if x > max_x:
                x = max_x
                self.particleVel[2 * i] = 0.0
            if y < min_y:
                y = min_y
                self.particleVel[2 * i + 1] = 0.0
            if y > max_y:
                y = max_y
                self.particleVel[2 * i + 1] = 0.0

            self.particlePos[2 * i] = x
            self.particlePos[2 * i + 1] = y

    def transfer_velocities(self, to_grid, flip_ratio=0.9):
        n = self.fNumY
        h = self.h
        h1 = self.fInvSpacing
        h2 = 0.5 * h

        if to_grid:
            self.prevU = list(self.u)
            self.prevV = list(self.v)
            self.du = [0.0] * self.fNumCells
            self.dv = [0.0] * self.fNumCells
            self.u = [0.0] * self.fNumCells
            self.v = [0.0] * self.fNumCells

            for i in range(self.fNumCells):
                self.cellType[i] = SOLID_CELL if self.s[i] == 0.0 else AIR_CELL

            for i in range(self.numParticles):
                x = self.particlePos[2 * i]
                y = self.particlePos[2 * i + 1]
                xi = clamp(int(x * h1), 0, self.fNumX - 1)
                yi = clamp(int(y * h1), 0, self.fNumY - 1)
                cell_nr = xi * n + yi
                if self.cellType[cell_nr] == AIR_CELL:
                    self.cellType[cell_nr] = FLUID_CELL

        for component in range(2):
            dx = 0.0 if component == 0 else h2
            dy = h2 if component == 0 else 0.0

            f = self.u if component == 0 else self.v
            prev_f = self.prevU if component == 0 else self.prevV
            d = self.du if component == 0 else self.dv

            for i in range(self.numParticles):
                x = self.particlePos[2 * i]
                y = self.particlePos[2 * i + 1]

                x = clamp(x, h, (self.fNumX - 1) * h)
                y = clamp(y, h, (self.fNumY - 1) * h)

                x0 = min(int((x - dx) * h1), self.fNumX - 2)
                tx = ((x - dx) - x0 * h) * h1
                x1 = min(x0 + 1, self.fNumX - 2)

                y0 = min(int((y - dy) * h1), self.fNumY - 2)
                ty = ((y - dy) - y0 * h) * h1
                y1 = min(y0 + 1, self.fNumY - 2)

                sx = 1.0 - tx
                sy = 1.0 - ty

                d0 = sx * sy
                d1 = tx * sy
                d2 = tx * ty
                d3 = sx * ty

                nr0 = x0 * n + y0
                nr1 = x1 * n + y0
                nr2 = x1 * n + y1
                nr3 = x0 * n + y1

                if to_grid:
                    pv = self.particleVel[2 * i + component]
                    f[nr0] += pv * d0;  d[nr0] += d0
                    f[nr1] += pv * d1;  d[nr1] += d1
                    f[nr2] += pv * d2;  d[nr2] += d2
                    f[nr3] += pv * d3;  d[nr3] += d3
                else:
                    offset = n if component == 0 else 1
                    valid0 = 1.0 if (self.cellType[nr0] != AIR_CELL or
                                     self.cellType[nr0 - offset] != AIR_CELL) else 0.0
                    valid1 = 1.0 if (self.cellType[nr1] != AIR_CELL or
                                     self.cellType[nr1 - offset] != AIR_CELL) else 0.0
                    valid2 = 1.0 if (self.cellType[nr2] != AIR_CELL or
                                     self.cellType[nr2 - offset] != AIR_CELL) else 0.0
                    valid3 = 1.0 if (self.cellType[nr3] != AIR_CELL or
                                     self.cellType[nr3 - offset] != AIR_CELL) else 0.0

                    v_old = self.particleVel[2 * i + component]
                    dd = valid0 * d0 + valid1 * d1 + valid2 * d2 + valid3 * d3

                    if dd > 0.0:
                        pic_v = (valid0 * d0 * f[nr0] + valid1 * d1 * f[nr1] +
                                 valid2 * d2 * f[nr2] + valid3 * d3 * f[nr3]) / dd
                        corr = (valid0 * d0 * (f[nr0] - prev_f[nr0]) +
                                valid1 * d1 * (f[nr1] - prev_f[nr1]) +
                                valid2 * d2 * (f[nr2] - prev_f[nr2]) +
                                valid3 * d3 * (f[nr3] - prev_f[nr3])) / dd
                        flip_v = v_old + corr
                        self.particleVel[2 * i + component] = \
                            (1.0 - flip_ratio) * pic_v + flip_ratio * flip_v

            if to_grid:
                for i in range(len(f)):
                    if d[i] > 0.0:
                        f[i] /= d[i]

                for i in range(self.fNumX):
                    for j in range(self.fNumY):
                        solid = self.cellType[i * n + j] == SOLID_CELL
                        if solid or (i > 0 and
                                     self.cellType[(i - 1) * n + j] == SOLID_CELL):
                            self.u[i * n + j] = self.prevU[i * n + j]
                        if solid or (j > 0 and
                                     self.cellType[i * n + j - 1] == SOLID_CELL):
                            self.v[i * n + j] = self.prevV[i * n + j]

    def update_particle_density(self):
        n = self.fNumY
        h = self.h
        h1 = self.fInvSpacing
        h2 = 0.5 * h

        self.particleDensity = [0.0] * self.fNumCells

        for i in range(self.numParticles):
            x = self.particlePos[2 * i]
            y = self.particlePos[2 * i + 1]

            x = clamp(x, h, (self.fNumX - 1) * h)
            y = clamp(y, h, (self.fNumY - 1) * h)

            x0 = int((x - h2) * h1)
            tx = ((x - h2) - x0 * h) * h1
            x1 = min(x0 + 1, self.fNumX - 2)

            y0 = int((y - h2) * h1)
            ty = ((y - h2) - y0 * h) * h1
            y1 = min(y0 + 1, self.fNumY - 2)

            sx = 1.0 - tx
            sy = 1.0 - ty

            if x0 < self.fNumX and y0 < self.fNumY:
                self.particleDensity[x0 * n + y0] += sx * sy
            if x1 < self.fNumX and y0 < self.fNumY:
                self.particleDensity[x1 * n + y0] += tx * sy
            if x1 < self.fNumX and y1 < self.fNumY:
                self.particleDensity[x1 * n + y1] += tx * ty
            if x0 < self.fNumX and y1 < self.fNumY:
                self.particleDensity[x0 * n + y1] += sx * ty

        if self.particleRestDensity == 0.0:
            sum_d = 0.0
            num_fluid = 0
            for i in range(self.fNumCells):
                if self.cellType[i] == FLUID_CELL:
                    sum_d += self.particleDensity[i]
                    num_fluid += 1
            if num_fluid > 0:
                self.particleRestDensity = sum_d / num_fluid

    def solve_incompressibility(self, num_iters, dt, over_relaxation=1.9,
                                compensate_drift=True):
        self.p = [0.0] * self.fNumCells
        self.prevU = list(self.u)
        self.prevV = list(self.v)

        n = self.fNumY
        cp = self.density * self.h / dt

        for _it in range(num_iters):
            for i in range(1, self.fNumX - 1):
                for j in range(1, self.fNumY - 1):
                    if self.cellType[i * n + j] != FLUID_CELL:
                        continue

                    center = i * n + j
                    left = (i - 1) * n + j
                    right = (i + 1) * n + j
                    bottom = i * n + j - 1
                    top = i * n + j + 1

                    sx0 = self.s[left]
                    sx1 = self.s[right]
                    sy0 = self.s[bottom]
                    sy1 = self.s[top]
                    s_sum = sx0 + sx1 + sy0 + sy1
                    if s_sum == 0.0:
                        continue

                    div = self.u[right] - self.u[center] + \
                          self.v[top] - self.v[center]

                    if self.particleRestDensity > 0.0 and compensate_drift:
                        compression = self.particleDensity[center] - \
                                      self.particleRestDensity
                        if compression > 0.0:
                            div = div - compression

                    p_corr = -div / s_sum
                    p_corr *= over_relaxation
                    self.p[center] += cp * p_corr

                    self.u[center] -= sx0 * p_corr
                    self.u[right] += sx1 * p_corr
                    self.v[center] -= sy0 * p_corr
                    self.v[top] += sy1 * p_corr

    def simulate(self, dt, gravity, flip_ratio, num_pressure_iters,
                 num_particle_iters, over_relaxation, compensate_drift,
                 separate_particles):
        self.integrate_particles(dt, gravity)
        if separate_particles:
            self.push_particles_apart(num_particle_iters)
        self.handle_collisions()
        self.transfer_velocities(True)
        self.update_particle_density()
        self.solve_incompressibility(num_pressure_iters, dt,
                                     over_relaxation, compensate_drift)
        self.transfer_velocities(False, flip_ratio)
