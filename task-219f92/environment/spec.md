# ETD4RK Exponential Integrator — Mathematical Specification

## Phi-functions

The phi-functions are defined by the recurrence:

    phi_0(z) = exp(z)
    phi_{k+1}(z) = (phi_k(z) - 1/k!) / z,  for k >= 0

Equivalently, in closed form:

    phi_1(z) = (exp(z) - 1) / z
    phi_2(z) = (exp(z) - 1 - z) / z^2
    phi_3(z) = (exp(z) - 1 - z - z^2/2) / z^3

Limiting values at z = 0 (removable singularity):

    phi_1(0) = 1,   phi_2(0) = 1/2,   phi_3(0) = 1/6

**Warning:** The closed-form expressions involve differences of nearly equal
quantities when |z| is small. Naive floating-point evaluation suffers
catastrophic cancellation. A numerically stable implementation is essential.


## ETD4RK Scheme

For the semi-discrete ODE system:

    du_hat/dt = L * u_hat + N(u_hat)

where L is a diagonal linear operator, the ETD4RK method advances one time
step of size h as follows.

**Stage values** (all operations element-wise for diagonal L):

    N_n = N(u_hat_n)

    a = exp(hL/2) * u_hat_n  +  (h/2) * phi_1(hL/2) * N_n
    b = exp(hL/2) * u_hat_n  +  (h/2) * phi_1(hL/2) * N(a)
    c = exp(hL/2) * a         +  (h/2) * phi_1(hL/2) * (2*N(b) - N_n)

**Update** (phi_k evaluated at hL):

    u_hat_{n+1} = exp(hL) * u_hat_n
        + h * [ (phi_1 - 3*phi_2 + 4*phi_3) * N_n
              + 2*(phi_2 - 2*phi_3) * (N(a) + N(b))
              + (-phi_2 + 4*phi_3) * N(c) ]


## Kuramoto-Sivashinsky Equation

    u_t + u * u_x + u_xx + u_xxxx = 0

on [0, L] with periodic boundary conditions. The Fourier spectral
discretization (provided in problem.py and octave/ks_setup.m) gives:

    Linear operator:  L_k = k^2 - k^4   (diagonal in Fourier space)
    Nonlinear term:   N(u_hat) = -(j*k/2) * FFT(u^2)

where k = 2*pi*m/L are the wavenumbers and u = Re(IFFT(u_hat)).


## Available Octave Functions

The following GNU Octave functions are provided in `/app/octave/`:

**phifun(z, k)** — Evaluate phi_k(z) for k = 0,1,2,3 using Taylor series
switching. Accepts scalar or vector z. Based on the EXPINT package.

**ks_setup(L, N)** — Returns [x, k, Lk, u0_hat] for the KS equation
discretized on [0, L] with N Fourier modes. Wavenumber ordering matches
numpy.fft.fftfreq. Initial condition: u0 = cos(x/16)*(1+sin(x/16)).


## Interface Requirements

Create `/app/solver.py` with:

```python
def phi(z, k):
    """Compute phi_k(z).

    Parameters:
        z: scalar or numpy array (real or complex)
        k: integer, 0 <= k <= 3

    Returns:
        phi_k(z), same shape as z
    """

def solve_ks(L=32*np.pi, N=128, T=1.0, dt=0.25):
    """Solve the KS equation using ETD4RK.

    Parameters:
        L: domain length
        N: number of Fourier modes
        T: final time
        dt: time step

    Returns:
        u(x, T) in physical space as a real numpy array of length N
    """
```


## Reference Data Specifications

The Octave reference generation script (`octave/gen_reference.m`) must produce
the following CSV files in `/app/reference/`:

**`phi_coeffs.csv`** — 16 rows × 5 columns.
Each row: z, phi_0(z), phi_1(z), phi_2(z), phi_3(z).
Use z values: [-100, -50, -20, -10, -5, -1, -0.5, -0.1, -1e-6, 0, 1e-6, 0.1, 0.5, 1, 2, 5].
Full double precision.

**`etd4rk_coeffs.csv`** — 6 rows × 4 columns.
Each row: hL, followed by the three update coefficients from the ETD4RK
update formula above, evaluated at that hL value.
Use hL values: [-50, -20, -10, -5, -1, -0.1].
Full double precision.

**`ks_ref.csv`** — 64 comma-separated values: the KS solution u(x, T=1.0)
with L=32π, N=64, computed via a stiff ODE solver at tolerance ≤ 1e-12.


## Accuracy Thresholds

- Phi-function values: Python vs Octave relative error < 1e-8
- Update coefficients: Python vs Octave relative error < 1e-8
- KS solution: Python vs Octave max absolute error < 0.01
