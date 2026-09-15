# Sedov-von Neumann-Taylor Blast Wave: Mathematical Formulation

## Problem Description

The Sedov blast wave describes the self-similar evolution of a strong shock wave
produced by an instantaneous point release of energy E_blast in a gas with
initial density profile rho_0 * r^(-omega).

The solution depends on: specific heat ratio gamma, geometry j (1=planar,
2=cylindrical, 3=spherical), initial density rho_0 and exponent omega, and
blast energy E_blast.

Reference: Kamm & Timmes (2000), "Evaluation of the Sedov-von Neumann-Taylor
Blast Wave Solution", LA-UR-00-6055, Los Alamos National Laboratory.

## Key Parameters

    gamm1 = gamma - 1
    gamp1 = gamma + 1
    gpogm = gamp1 / gamm1
    xg2   = j + 2 - omega       (j = geometry)

    denom2 = 2*gamm1 + j - gamma*omega
    denom3 = j*(2 - gamma) - omega

Post-shock similarity variable:

    v2    = 4 / (xg2 * gamp1)
    vstar = 2 / (gamm1 * j + 2)

## Solution Types

- Standard: v2 < vstar  (typical case)
- Singular: v2 ~ vstar  (transition, analytic solution)
- Vacuum:   v2 > vstar  (vacuum forms behind shock)

For standard case, the origin in v-space is at:
    v0 = 2 / (xg2 * gamma)

For vacuum case, the vacuum boundary in v-space is at:
    vv = 2 / xg2

## Exponents (Kamm Equations 42-47)

    a0 = 2 / xg2

    a2 = -gamm1 / denom2

    a1 = xg2*gamma / (2 + j*gamm1) * (2*(j*(2-gamma) - omega) / (gamma*xg2^2) - a2)

    a3 = (j - omega) / denom2

    a4 = xg2*(j - omega)*a1 / denom3

    a5 = (omega*gamp1 - 2*j) / denom3

## Combination Variables (Kamm Equations 29-37)

    A = xg2*gamp1 / 4
    B = gpogm
    C = xg2*gamma / 2
    D = xg2*gamp1 / (xg2*gamp1 - 2*(2 + j*gamm1))
    E = (2 + j*gamm1) / 2

Given similarity variable v, define:

    x1 = A * v
    x2 = B * max(C*v - 1, eps)
    x3 = D * (1 - E*v)
    x4 = B * (1 - xg2*v/2)

## Sedov Functions: Standard Case (Kamm Equations 38-41)

    lambda(v) = x1^(-a0) * x2^(-a2) * x3^(-a1)

    f(v) = x1 * lambda(v)                                   [velocity V]

    g(v) = x1^(a0*omega) * x2^(a3+a2*omega)
           * x3^(a4+a1*omega) * x4^(a5)                     [density D]

    h(v) = x1^(a0*j) * x3^(a4+a1*(omega-2))
           * x4^(1+a5)                                      [pressure P]

    d(lambda)/dv = -(a0*A/x1 + a2*B*C/x2 + a1*(-D*E)/x3) * lambda

## Energy Integrals

First energy integral:
    eval1 = integral from vmin to v2 of:
            (d_lambda/dv) * lambda^(j+1) * gpogm * g(v) * v^2  dv

Second energy integral:
    eval2 = integral from vmin to v2 of:
            (d_lambda/dv) * lambda^(j-1) * h(v) * 8/(xg2^2 * gamp1)  dv

where vmin = v0 (standard) or vv (vacuum).

Energy normalization constant alpha:
    Planar (j=1):      alpha = eval1/2 + eval2/gamm1
    Cylindrical (j=2): alpha = pi * (eval1 + 2*eval2/gamm1)
    Spherical (j=3):   alpha = 2*pi * (eval1 + 2*eval2/gamm1)

For singular case, alpha has analytic form:
    alpha = gpogm * 2^j / (j * (gamm1*j + 2)^2)
    multiply by pi if j > 1

## Shock Jump Conditions

Shock position at time t:
    r2 = (E_blast / (alpha * rho_0))^(1/xg2) * t^(2/xg2)

Shock velocity:
    us = (2/xg2) * r2 / t

Post-shock values:
    u2   = 2 * us / gamp1
    rho2 = gpogm * rho_0 * r2^(-omega)
    p2   = 2 * rho_0 * r2^(-omega) * us^2 / gamp1

Physical variables at radius r (where r <= r2):
    velocity = u2 * f(v)
    density  = rho2 * g(v)
    pressure = p2 * h(v)

where v is found by solving lambda(v) = r/r2.

## Special Singularity Cases

When denom2 ~ 0 (omega2 case) or denom3 ~ 0 (omega3 case), the standard
Sedov function expressions become singular. Modified expressions using
exponential terms are required. See Kamm & Timmes equations 20-25.

## Singular Solution Type

When v2 ~ vstar, the Sedov functions simplify to:
    lambda = r/r2
    f = lambda
    g = lambda^(j-2)
    h = lambda^j

## Reference Data Tables

### Table 1: Sedov Functions, Planar (j=1), gamma=1.4, omega=0

lambda   v       f       g       h
0.9797   0.5500  0.9699  0.8620  0.9159
0.9420   0.5400  0.9157  0.6662  0.7917
0.9013   0.5300  0.8598  0.5159  0.6922
0.8565   0.5200  0.8017  0.3981  0.6119
0.8050   0.5100  0.7390  0.3020  0.5458
0.7419   0.5000  0.6677  0.2201  0.4905
0.7029   0.4950  0.6263  0.1823  0.4661
0.6553   0.4900  0.5780  0.1453  0.4437
0.5925   0.4850  0.5173  0.1075  0.4230
0.5396   0.4820  0.4682  0.0826  0.4112
0.4912   0.4800  0.4244  0.0641  0.4037
0.4589   0.4790  0.3957  0.0535  0.4001
0.4161   0.4780  0.3580  0.0415  0.3964
0.3480   0.4770  0.2988  0.0263  0.3929
0.2810   0.4765  0.2410  0.0153  0.3911
0.2320   0.4763  0.1989  0.0095  0.3905
0.1680   0.4762  0.1440  0.0042  0.3901
0.1040   0.4762  0.0891  0.0013  0.3900

### Table 2: Sedov Functions, Cylindrical (j=2), gamma=1.4, omega=0

lambda   v       f       g       h
0.9998   0.4166  0.9996  0.9972  0.9984
0.9802   0.4100  0.9645  0.7651  0.8658
0.9644   0.4050  0.9374  0.6281  0.7829
0.9476   0.4000  0.9097  0.5161  0.7122
0.9295   0.3950  0.8812  0.4233  0.6513
0.9096   0.3900  0.8514  0.3450  0.5982
0.8725   0.3820  0.7999  0.2427  0.5266
0.8442   0.3770  0.7638  0.1892  0.4884
0.8094   0.3720  0.7226  0.1415  0.4545
0.7629   0.3670  0.6720  0.0974  0.4241
0.7242   0.3640  0.6327  0.0718  0.4074
0.6894   0.3620  0.5990  0.0545  0.3969
0.6390   0.3600  0.5521  0.0362  0.3867
0.5745   0.3585  0.4943  0.0208  0.3794
0.5180   0.3578  0.4448  0.0123  0.3760
0.4748   0.3575  0.4074  0.0079  0.3746
0.4222   0.3573  0.3620  0.0044  0.3737
0.3654   0.3572  0.3133  0.0021  0.3732
0.3000   0.3572  0.2572  0.0008  0.3730
0.2500   0.3571  0.2143  0.0003  0.3729
0.2000   0.3571  0.1714  0.0001  0.3729
0.1500   0.3571  0.1286  0.0000  0.3729
0.1000   0.3571  0.0857  0.0000  0.3729

### Table 3: Sedov Functions, Spherical (j=3), gamma=1.4, omega=0

lambda   v       f       g       h
0.9913   0.3300  0.9814  0.8388  0.9116
0.9773   0.3250  0.9529  0.6454  0.7992
0.9622   0.3200  0.9238  0.4984  0.7082
0.9342   0.3120  0.8745  0.3248  0.5929
0.9080   0.3060  0.8335  0.2275  0.5238
0.8747   0.3000  0.7872  0.1508  0.4674
0.8359   0.2950  0.7398  0.0968  0.4273
0.7950   0.2915  0.6952  0.0620  0.4021
0.7493   0.2890  0.6497  0.0379  0.3857
0.6788   0.2870  0.5844  0.0174  0.3732
0.5794   0.2860  0.4971  0.0052  0.3672
0.4560   0.2857  0.3909  0.0009  0.3656
0.3600   0.2857  0.3086  0.0001  0.3655
0.2960   0.2857  0.2537  0.0000  0.3655
0.2000   0.2857  0.1714  0.0000  0.3655
0.1040   0.2857  0.0891  0.0000  0.3655

### Table 4: Energy Integrals, gamma=1.4, omega=0

geometry   eval1        eval2        alpha
1 (plan.)  0.197928     0.175834     0.538548
2 (cyl.)   6.54053e-02  4.95650e-02  9.84041e-01
3 (sph.)   2.96269e-02  2.11647e-02  8.51060e-01

### Table 5: Shock Values at t=1, gamma=1.4, omega=0

geometry  eblast        r2    rho2  u2        p2
1         6.73185e-02   0.5   6.0   2.778e-1  9.259e-2
2         3.11357e-01   0.75  6.0   3.125e-1  1.172e-1
3         8.51072e-01   1.0   6.0   3.333e-1  1.333e-1

### Table 6: Singular Case Alpha Values

geometry  omega     alpha
2         1.66667   4.80856
3         2.33333   4.90875

### Table 8: Vacuum Case Values, gamma=1.4

geometry  omega  eval1     eval2     alpha
2         1.7    0.856238  0.158561  5.18062
3         2.4    0.454265  0.082839  5.45670
