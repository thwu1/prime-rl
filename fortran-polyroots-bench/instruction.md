Build a polynomial root-finding benchmark at `/app/` using the [polyroots-fortran](https://github.com/jacobwilliams/polyroots-fortran) library. The environment has `gfortran`, LAPACK, and BLAS pre-installed. A clone of polyroots-fortran is at `/opt/polyroots-fortran`.

Consider the near-degenerate polynomial P(x) = (x-1)^8 + 10^{-4} with coefficients in descending powers:

```
[1, -8, 28, -56, 70, -56, 28, -8, 1.0001]
```

Find all roots of this polynomial using every general-purpose real-coefficient root-finding method available in polyroots-fortran, at both double precision (`real64`) and quad precision (`real128`). Examine the library source to identify all available methods, their calling conventions, and how to build the library at each precision level. Some methods may not support all precision levels — handle such cases gracefully.

For each successful method, compute the maximum backward error max_k |P(z_k)| across all computed roots. Sort roots by real part ascending, breaking ties by imaginary part ascending.

Write `/app/results.json` with this structure:

```json
{
  "real64": {
    "methods": {
      "<method_name>": {
        "max_backward_error": <float>,
        "roots": [{"real": <float>, "imag": <float>}, ...],
        "status": 0
      },
      ...
    },
    "best_method": "<method_name_with_smallest_max_backward_error>"
  },
  "real128": {
    "methods": { ... },
    "best_method": "..."
  }
}
```

Failed methods should have `"status"` set to a non-zero integer, `"max_backward_error": null`, and `"roots": []`.