# Wavelet Kernel Reference

## Meyer Wavelet

The Meyer wavelet system forms a **tight frame** (A = B = 1), which
guarantees perfect reconstruction through analysis followed by
synthesis.

### Auxiliary polynomial

The smooth transition between pass-band and stop-band is governed by
the polynomial:

    v(x) = x^4 (35 - 84 x + 70 x^2 - 20 x^3)

This polynomial satisfies  v(0) = 0,  v(1) = 1  and has vanishing
derivatives at both endpoints, providing C^3 regularity.

### Scaling function (low-pass)

    phi(x) = 1                              for  x in [0, 2/3)
    phi(x) = cos( pi/2  v(3|x|/2 - 1) )    for  x in [2/3, 4/3)
    phi(x) = 0                              otherwise

### Wavelet (band-pass)

    psi(x) = sin( pi/2  v(3|x|/2 - 1) )    for  x in [2/3, 4/3)
    psi(x) = cos( pi/2  v(3|x|/4 - 1) )    for  x in [4/3, 8/3)
    psi(x) = 0                              otherwise

### Dyadic scales

For a filterbank with Nf filters the Meyer system uses Nf - 1 dyadic
scales:

    s_k = (4 / (3 lambda_max)) * 2^k    for k = Nf-2, ..., 0

The first filter is the scaling function evaluated at scale s_0.
Filters 1 through Nf-1 are the wavelet evaluated at s_0, ..., s_{Nf-2}.

---

## MexicanHat Wavelet

### Low-pass (scaling function)

    h(lambda) = 1.2 * exp(-1) * exp( -(lambda / (0.4 * lmin))^4 )

where  lmin = lmax / lpfactor.

### Band-pass at scale s

    g(lambda) = s * lambda * exp(-s * lambda)

### Log-spaced scales

The scales are computed by evenly spacing in the log domain between
bounds derived from lmin and lmax:

    scale_min = t1 / lmax
    scale_max = t2 / lmin
    scales = exp( linspace( log(scale_max), log(scale_min), Nscales ) )
