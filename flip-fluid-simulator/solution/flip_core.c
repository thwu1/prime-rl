/* FLIP Fluid Simulator — C Implementation
 */

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define FLUID_CELL 0
#define AIR_CELL   1
#define SOLID_CELL 2

typedef struct {
    double density;
    int fNumX, fNumY, fNumCells;
    double h, fInvSpacing;

    double *u, *v, *du, *dv;
    double *prevU, *prevV;
    double *p, *s;
    int *cellType;
    double *particleDensity;

    int maxParticles, numParticles;
    double *particlePos, *particleVel;
    double particleRadius;
    double particleRestDensity;

    double pInvSpacing;
    int pNumX, pNumY, pNumCells;
    int *numCellParticles, *firstCellParticle, *cellParticleIds;

    /* Diagnostics */
    int lastSubsteps;
    double lastMaxDivergence;
    int lastPressureIters;
} FlipFluid;

static inline double dclamp(double x, double lo, double hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}
static inline int iclamp(int x, int lo, int hi) {
    return x < lo ? lo : (x > hi ? hi : x);
}
static inline int imin(int a, int b) { return a < b ? a : b; }
static inline int imax(int a, int b) { return a > b ? a : b; }

/* ------------------------------------------------------------------ */
/* Creation / Destruction                                              */
/* ------------------------------------------------------------------ */

FlipFluid* flip_create(double density, double width, double height,
                       double spacing, double particleRadius, int maxParticles) {
    FlipFluid* f = (FlipFluid*)calloc(1, sizeof(FlipFluid));
    f->density = density;
    f->fNumX = (int)(width / spacing) + 1;
    f->fNumY = (int)(height / spacing) + 1;
    double hx = width / (double)f->fNumX;
    double hy = height / (double)f->fNumY;
    f->h = hx > hy ? hx : hy;
    f->fInvSpacing = 1.0 / f->h;
    f->fNumCells = f->fNumX * f->fNumY;

    f->u    = (double*)calloc(f->fNumCells, sizeof(double));
    f->v    = (double*)calloc(f->fNumCells, sizeof(double));
    f->du   = (double*)calloc(f->fNumCells, sizeof(double));
    f->dv   = (double*)calloc(f->fNumCells, sizeof(double));
    f->prevU = (double*)calloc(f->fNumCells, sizeof(double));
    f->prevV = (double*)calloc(f->fNumCells, sizeof(double));
    f->p    = (double*)calloc(f->fNumCells, sizeof(double));
    f->s    = (double*)calloc(f->fNumCells, sizeof(double));
    f->cellType = (int*)calloc(f->fNumCells, sizeof(int));
    f->particleDensity = (double*)calloc(f->fNumCells, sizeof(double));

    f->maxParticles = maxParticles;
    f->numParticles = 0;
    f->particlePos = (double*)calloc(2 * maxParticles, sizeof(double));
    f->particleVel = (double*)calloc(2 * maxParticles, sizeof(double));
    f->particleRadius = particleRadius;
    f->particleRestDensity = 0.0;

    f->pInvSpacing = 1.0 / (2.2 * particleRadius);
    f->pNumX = (int)(width * f->pInvSpacing) + 1;
    f->pNumY = (int)(height * f->pInvSpacing) + 1;
    f->pNumCells = f->pNumX * f->pNumY;
    f->numCellParticles  = (int*)calloc(f->pNumCells, sizeof(int));
    f->firstCellParticle = (int*)calloc(f->pNumCells + 1, sizeof(int));
    f->cellParticleIds   = (int*)calloc(maxParticles, sizeof(int));

    f->lastSubsteps = 0;
    f->lastMaxDivergence = 0.0;
    f->lastPressureIters = 0;

    return f;
}

void flip_destroy(FlipFluid* f) {
    if (!f) return;
    free(f->u); free(f->v); free(f->du); free(f->dv);
    free(f->prevU); free(f->prevV);
    free(f->p); free(f->s); free(f->cellType);
    free(f->particleDensity);
    free(f->particlePos); free(f->particleVel);
    free(f->numCellParticles); free(f->firstCellParticle);
    free(f->cellParticleIds);
    free(f);
}

/* ------------------------------------------------------------------ */
/* Simulation steps                                                    */
/* ------------------------------------------------------------------ */

static void integrate_particles(FlipFluid* f, double dt, double gravity) {
    int i;
    for (i = 0; i < f->numParticles; i++) {
        f->particleVel[2*i + 1] += dt * gravity;
        f->particlePos[2*i]     += f->particleVel[2*i] * dt;
        f->particlePos[2*i + 1] += f->particleVel[2*i + 1] * dt;
    }
}

static void push_particles_apart(FlipFluid* f, int numIters) {
    int i, iter;

    memset(f->numCellParticles, 0, f->pNumCells * sizeof(int));

    for (i = 0; i < f->numParticles; i++) {
        double x = f->particlePos[2*i];
        double y = f->particlePos[2*i + 1];
        int xi = iclamp((int)floor(x * f->pInvSpacing), 0, f->pNumX - 1);
        int yi = iclamp((int)floor(y * f->pInvSpacing), 0, f->pNumY - 1);
        int cellNr = xi * f->pNumY + yi;
        f->numCellParticles[cellNr]++;
    }

    int first = 0;
    for (i = 0; i < f->pNumCells; i++) {
        first += f->numCellParticles[i];
        f->firstCellParticle[i] = first;
    }
    f->firstCellParticle[f->pNumCells] = first;

    for (i = 0; i < f->numParticles; i++) {
        double x = f->particlePos[2*i];
        double y = f->particlePos[2*i + 1];
        int xi = iclamp((int)floor(x * f->pInvSpacing), 0, f->pNumX - 1);
        int yi = iclamp((int)floor(y * f->pInvSpacing), 0, f->pNumY - 1);
        int cellNr = xi * f->pNumY + yi;
        f->firstCellParticle[cellNr]--;
        f->cellParticleIds[f->firstCellParticle[cellNr]] = i;
    }

    double minDist = 2.0 * f->particleRadius;
    double minDist2 = minDist * minDist;

    for (iter = 0; iter < numIters; iter++) {
        for (i = 0; i < f->numParticles; i++) {
            double px = f->particlePos[2*i];
            double py = f->particlePos[2*i + 1];

            int pxi = (int)floor(px * f->pInvSpacing);
            int pyi = (int)floor(py * f->pInvSpacing);
            int x0 = imax(pxi - 1, 0);
            int y0 = imax(pyi - 1, 0);
            int x1 = imin(pxi + 1, f->pNumX - 1);
            int y1 = imin(pyi + 1, f->pNumY - 1);

            int xi, yi;
            for (xi = x0; xi <= x1; xi++) {
                for (yi = y0; yi <= y1; yi++) {
                    int cellNr = xi * f->pNumY + yi;
                    int fp = f->firstCellParticle[cellNr];
                    int lp = f->firstCellParticle[cellNr + 1];
                    int j;
                    for (j = fp; j < lp; j++) {
                        int pid = f->cellParticleIds[j];
                        if (pid == i) continue;
                        double ddx = f->particlePos[2*pid]     - px;
                        double ddy = f->particlePos[2*pid + 1] - py;
                        double d2 = ddx*ddx + ddy*ddy;
                        if (d2 > minDist2 || d2 == 0.0) continue;
                        double d = sqrt(d2);
                        double s = 0.5 * (minDist - d) / d;
                        ddx *= s;
                        ddy *= s;
                        f->particlePos[2*i] -= ddx;
                        f->particlePos[2*i + 1] -= ddy;
                        f->particlePos[2*pid] += ddx;
                        f->particlePos[2*pid + 1] += ddy;
                    }
                }
            }
        }
    }
}

static void handle_collisions(FlipFluid* f) {
    double h = 1.0 / f->fInvSpacing;
    double r = f->particleRadius;
    double minX = h + r;
    double maxX = (f->fNumX - 1) * h - r;
    double minY = h + r;
    double maxY = (f->fNumY - 1) * h - r;

    int i;
    for (i = 0; i < f->numParticles; i++) {
        double x = f->particlePos[2*i];
        double y = f->particlePos[2*i + 1];

        if (x < minX) { x = minX; f->particleVel[2*i] = 0.0; }
        if (x > maxX) { x = maxX; f->particleVel[2*i] = 0.0; }
        if (y < minY) { y = minY; f->particleVel[2*i + 1] = 0.0; }
        if (y > maxY) { y = maxY; f->particleVel[2*i + 1] = 0.0; }

        f->particlePos[2*i]     = x;
        f->particlePos[2*i + 1] = y;
    }
}

static void transfer_velocities(FlipFluid* f, int toGrid, double flipRatio) {
    int n = f->fNumY;
    double h  = f->h;
    double h1 = f->fInvSpacing;
    double h2 = 0.5 * h;
    int i, j, component;

    if (toGrid) {
        memcpy(f->prevU, f->u, f->fNumCells * sizeof(double));
        memcpy(f->prevV, f->v, f->fNumCells * sizeof(double));
        memset(f->du, 0, f->fNumCells * sizeof(double));
        memset(f->dv, 0, f->fNumCells * sizeof(double));
        memset(f->u,  0, f->fNumCells * sizeof(double));
        memset(f->v,  0, f->fNumCells * sizeof(double));

        for (i = 0; i < f->fNumCells; i++)
            f->cellType[i] = (f->s[i] == 0.0) ? SOLID_CELL : AIR_CELL;

        for (i = 0; i < f->numParticles; i++) {
            double x = f->particlePos[2*i];
            double y = f->particlePos[2*i + 1];
            int xi = iclamp((int)floor(x * h1), 0, f->fNumX - 1);
            int yi = iclamp((int)floor(y * h1), 0, f->fNumY - 1);
            int cellNr = xi * n + yi;
            if (f->cellType[cellNr] == AIR_CELL)
                f->cellType[cellNr] = FLUID_CELL;
        }
    }

    for (component = 0; component < 2; component++) {
        double dx = (component == 0) ? 0.0 : h2;
        double dy = (component == 0) ? h2  : 0.0;

        double* ff    = (component == 0) ? f->u    : f->v;
        double* prevF = (component == 0) ? f->prevU : f->prevV;
        double* d     = (component == 0) ? f->du   : f->dv;

        for (i = 0; i < f->numParticles; i++) {
            double x = f->particlePos[2*i];
            double y = f->particlePos[2*i + 1];

            x = dclamp(x, h, (f->fNumX - 1) * h);
            y = dclamp(y, h, (f->fNumY - 1) * h);

            int x0 = imin((int)floor((x - dx) * h1), f->fNumX - 2);
            double tx = ((x - dx) - x0 * h) * h1;
            int x1 = imin(x0 + 1, f->fNumX - 2);

            int y0 = imin((int)floor((y - dy) * h1), f->fNumY - 2);
            double ty = ((y - dy) - y0 * h) * h1;
            int y1 = imin(y0 + 1, f->fNumY - 2);

            double sx = 1.0 - tx;
            double sy = 1.0 - ty;

            double d0 = sx * sy;
            double d1 = tx * sy;
            double d2 = tx * ty;
            double d3 = sx * ty;

            int nr0 = x0 * n + y0;
            int nr1 = x1 * n + y0;
            int nr2 = x1 * n + y1;
            int nr3 = x0 * n + y1;

            if (toGrid) {
                double pv = f->particleVel[2*i + component];
                ff[nr0] += pv * d0; d[nr0] += d0;
                ff[nr1] += pv * d1; d[nr1] += d1;
                ff[nr2] += pv * d2; d[nr2] += d2;
                ff[nr3] += pv * d3; d[nr3] += d3;
            } else {
                int offset = (component == 0) ? n : 1;
                double valid0 = (f->cellType[nr0] != AIR_CELL ||
                                 f->cellType[nr0 - offset] != AIR_CELL) ? 1.0 : 0.0;
                double valid1 = (f->cellType[nr1] != AIR_CELL ||
                                 f->cellType[nr1 - offset] != AIR_CELL) ? 1.0 : 0.0;
                double valid2 = (f->cellType[nr2] != AIR_CELL ||
                                 f->cellType[nr2 - offset] != AIR_CELL) ? 1.0 : 0.0;
                double valid3 = (f->cellType[nr3] != AIR_CELL ||
                                 f->cellType[nr3 - offset] != AIR_CELL) ? 1.0 : 0.0;

                double vOld = f->particleVel[2*i + component];
                double dd = valid0*d0 + valid1*d1 + valid2*d2 + valid3*d3;

                if (dd > 0.0) {
                    double picV = (valid0*d0*ff[nr0] + valid1*d1*ff[nr1] +
                                   valid2*d2*ff[nr2] + valid3*d3*ff[nr3]) / dd;
                    double corr = (valid0*d0*(ff[nr0] - prevF[nr0]) +
                                   valid1*d1*(ff[nr1] - prevF[nr1]) +
                                   valid2*d2*(ff[nr2] - prevF[nr2]) +
                                   valid3*d3*(ff[nr3] - prevF[nr3])) / dd;
                    double flipV = vOld + corr;
                    f->particleVel[2*i + component] =
                        (1.0 - flipRatio) * picV + flipRatio * flipV;
                }
            }
        }

        if (toGrid) {
            int nc = f->fNumCells;
            for (i = 0; i < nc; i++) {
                if (d[i] > 0.0)
                    ff[i] /= d[i];
            }

            for (i = 0; i < f->fNumX; i++) {
                for (j = 0; j < f->fNumY; j++) {
                    int solid = (f->cellType[i*n + j] == SOLID_CELL);
                    if (solid || (i > 0 && f->cellType[(i-1)*n + j] == SOLID_CELL))
                        f->u[i*n + j] = f->prevU[i*n + j];
                    if (solid || (j > 0 && f->cellType[i*n + j - 1] == SOLID_CELL))
                        f->v[i*n + j] = f->prevV[i*n + j];
                }
            }
        }
    }
}

static void update_particle_density(FlipFluid* f) {
    int n = f->fNumY;
    double h  = f->h;
    double h1 = f->fInvSpacing;
    double h2 = 0.5 * h;
    int i;

    memset(f->particleDensity, 0, f->fNumCells * sizeof(double));

    for (i = 0; i < f->numParticles; i++) {
        double x = f->particlePos[2*i];
        double y = f->particlePos[2*i + 1];

        x = dclamp(x, h, (f->fNumX - 1) * h);
        y = dclamp(y, h, (f->fNumY - 1) * h);

        int x0 = (int)floor((x - h2) * h1);
        double tx = ((x - h2) - x0 * h) * h1;
        int x1 = imin(x0 + 1, f->fNumX - 2);

        int y0 = (int)floor((y - h2) * h1);
        double ty = ((y - h2) - y0 * h) * h1;
        int y1 = imin(y0 + 1, f->fNumY - 2);

        double sx = 1.0 - tx;
        double sy = 1.0 - ty;

        if (x0 < f->fNumX && y0 < f->fNumY)
            f->particleDensity[x0*n + y0] += sx * sy;
        if (x1 < f->fNumX && y0 < f->fNumY)
            f->particleDensity[x1*n + y0] += tx * sy;
        if (x1 < f->fNumX && y1 < f->fNumY)
            f->particleDensity[x1*n + y1] += tx * ty;
        if (x0 < f->fNumX && y1 < f->fNumY)
            f->particleDensity[x0*n + y1] += sx * ty;
    }

    if (f->particleRestDensity == 0.0) {
        double sumD = 0.0;
        int numFluid = 0;
        for (i = 0; i < f->fNumCells; i++) {
            if (f->cellType[i] == FLUID_CELL) {
                sumD += f->particleDensity[i];
                numFluid++;
            }
        }
        if (numFluid > 0)
            f->particleRestDensity = sumD / (double)numFluid;
    }
}

static void solve_incompressibility(FlipFluid* f, int numIters, double dt,
                                     double overRelaxation, int compensateDrift) {
    int n = f->fNumY;
    double cp = f->density * f->h / dt;
    int iter, i, j;
    int actualIters = 0;
    double maxDiv = 0.0;

    memset(f->p, 0, f->fNumCells * sizeof(double));
    memcpy(f->prevU, f->u, f->fNumCells * sizeof(double));
    memcpy(f->prevV, f->v, f->fNumCells * sizeof(double));

    for (iter = 0; iter < numIters; iter++) {
        for (i = 1; i < f->fNumX - 1; i++) {
            for (j = 1; j < f->fNumY - 1; j++) {
                if (f->cellType[i*n + j] != FLUID_CELL)
                    continue;

                int center = i*n + j;
                int left   = (i-1)*n + j;
                int right  = (i+1)*n + j;
                int bottom = i*n + j - 1;
                int top    = i*n + j + 1;

                double sx0 = f->s[left];
                double sx1 = f->s[right];
                double sy0 = f->s[bottom];
                double sy1 = f->s[top];
                double sSum = sx0 + sx1 + sy0 + sy1;
                if (sSum == 0.0) continue;

                double div = f->u[right] - f->u[center] +
                             f->v[top]   - f->v[center];

                if (f->particleRestDensity > 0.0 && compensateDrift) {
                    double compression = f->particleDensity[center] -
                                         f->particleRestDensity;
                    if (compression > 0.0)
                        div -= compression;
                }

                double pCorr = -(div / sSum) * overRelaxation;
                f->p[center] += cp * pCorr;

                f->u[center] -= sx0 * pCorr;
                f->u[right]  += sx1 * pCorr;
                f->v[center] -= sy0 * pCorr;
                f->v[top]    += sy1 * pCorr;
            }
        }

        actualIters = iter + 1;

        /* Compute max |divergence| for convergence check */
        maxDiv = 0.0;
        for (i = 1; i < f->fNumX - 1; i++) {
            for (j = 1; j < f->fNumY - 1; j++) {
                if (f->cellType[i*n + j] != FLUID_CELL) continue;
                int center = i*n + j;
                double div = f->u[(i+1)*n + j] - f->u[center] +
                             f->v[i*n + j + 1] - f->v[center];
                double ad = fabs(div);
                if (ad > maxDiv) maxDiv = ad;
            }
        }

        if (maxDiv < 1e-6) break;
    }

    f->lastMaxDivergence = maxDiv;
    f->lastPressureIters = actualIters;
}

/* ------------------------------------------------------------------ */
/* Public entry point                                                  */
/* ------------------------------------------------------------------ */

void flip_simulate(FlipFluid* f, double dt, double gravity, double flipRatio,
                   int numPressureIters, int numParticleIters,
                   double overRelaxation, int compensateDrift,
                   int separateParticles) {
    int i, step;
    double maxVel2 = 0.0, maxVel, cfl, sdt;
    int numSubSteps = 1;

    /* Compute max particle velocity for CFL condition */
    for (i = 0; i < f->numParticles; i++) {
        double vx = f->particleVel[2*i];
        double vy = f->particleVel[2*i + 1];
        double v2 = vx*vx + vy*vy;
        if (v2 > maxVel2) maxVel2 = v2;
    }
    maxVel = sqrt(maxVel2);

    /* CFL-based adaptive sub-stepping */
    if (f->h > 0.0 && maxVel > 0.0) {
        cfl = maxVel * dt / f->h;
        if (cfl > 1.0)
            numSubSteps = (int)ceil(cfl);
    }
    f->lastSubsteps = numSubSteps;

    sdt = dt / (double)numSubSteps;

    for (step = 0; step < numSubSteps; step++) {
        integrate_particles(f, sdt, gravity);
        if (separateParticles)
            push_particles_apart(f, numParticleIters);
        handle_collisions(f);
        transfer_velocities(f, 1, flipRatio);
        update_particle_density(f);
        solve_incompressibility(f, numPressureIters, sdt, overRelaxation,
                                compensateDrift);
        transfer_velocities(f, 0, flipRatio);
    }
}

/* ------------------------------------------------------------------ */
/* Accessor functions for ctypes                                       */
/* ------------------------------------------------------------------ */

int     flip_get_num_particles(FlipFluid* f)         { return f->numParticles; }
void    flip_set_num_particles(FlipFluid* f, int n)  { f->numParticles = n; }
int     flip_get_fNumX(FlipFluid* f)                 { return f->fNumX; }
int     flip_get_fNumY(FlipFluid* f)                 { return f->fNumY; }
int     flip_get_fNumCells(FlipFluid* f)             { return f->fNumCells; }
double  flip_get_h(FlipFluid* f)                     { return f->h; }
double  flip_get_fInvSpacing(FlipFluid* f)           { return f->fInvSpacing; }
double  flip_get_particle_radius(FlipFluid* f)       { return f->particleRadius; }

double* flip_get_particle_pos(FlipFluid* f)          { return f->particlePos; }
double* flip_get_particle_vel(FlipFluid* f)          { return f->particleVel; }
double* flip_get_u(FlipFluid* f)                     { return f->u; }
double* flip_get_v(FlipFluid* f)                     { return f->v; }
double* flip_get_s(FlipFluid* f)                     { return f->s; }
int*    flip_get_cell_type(FlipFluid* f)             { return f->cellType; }
double* flip_get_particle_density(FlipFluid* f)      { return f->particleDensity; }

/* Diagnostic accessors */
int     flip_get_last_substeps(FlipFluid* f)         { return f->lastSubsteps; }
double  flip_get_last_max_divergence(FlipFluid* f)   { return f->lastMaxDivergence; }
int     flip_get_last_pressure_iters(FlipFluid* f)   { return f->lastPressureIters; }
