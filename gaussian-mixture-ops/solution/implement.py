#!/usr/bin/env python3
"""
Implement all GM operations by filling in function stubs in gm_ops.py,
completing the C extension in gm_logpdf.c, and compiling the shared library.

"""
import re
import subprocess

SRC = "/app/gm_ops.py"

with open(SRC) as f:
    code = f.read()

# ------------------------------------------------------------------ helpers

def _replace_body(code, func_name, new_body):
    """Replace the NotImplementedError stub inside *func_name* with *new_body*."""
    pattern = re.compile(
        r'(def\s+' + func_name + r'\s*\(.*?\n)'
        r'(.*?)'
        r'(    raise NotImplementedError\([^\)]*\))',
        re.DOTALL,
    )
    m = pattern.search(code)
    if m is None:
        raise RuntimeError(f"Could not find NotImplementedError in {func_name}")
    return code[:m.start(3)] + new_body.rstrip() + code[m.end(3):]


# ===================================================================
# 1. gm_nll_loss
# ===================================================================
code = _replace_body(code, "gm_nll_loss", """\
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    inverse_stds = torch.exp(-logstds).clamp(max=1.0 / eps)
    diff_weighted = (samples.unsqueeze(-2) - means) * inverse_stds
    gaussian_ll = (-0.5 * diff_weighted.square() - logstds).sum(dim=-1)
    gm_nll = -torch.logsumexp(gaussian_ll + logweights.squeeze(-1), dim=-1)
    return gm_nll""")

# ===================================================================
# 2. gm_to_iso_gaussian
# ===================================================================
code = _replace_body(code, "gm_to_iso_gaussian", """\
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    weights = logweights.softmax(dim=1)
    gm_vars = (logstds * 2).exp()

    g_mean = (weights * means).sum(dim=1)

    diffs = means - g_mean.unsqueeze(1)
    spread = (weights * diffs.square()).sum(dim=1)
    g_var = spread.mean(dim=-1, keepdim=True) + gm_vars.squeeze(1)

    return {'mean': g_mean, 'var': g_var}""")

# ===================================================================
# 3. gm_mul_iso_gaussian
# ===================================================================
code = _replace_body(code, "gm_mul_iso_gaussian", """\
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    gm_vars = (logstds * 2).exp()

    g_mean = gaussian['mean']
    g_var = gaussian['var']
    g_logstd = 0.5 * torch.log(g_var)

    power_ratio = gaussian_power / gm_power
    norm_factor = (g_var.unsqueeze(1) + power_ratio * gm_vars).clamp(min=eps)

    out_means = (g_var.unsqueeze(1) * means
                 + power_ratio * gm_vars * g_mean.unsqueeze(1)) / norm_factor

    gm_diffs = means - g_mean.unsqueeze(1)
    logweights_delta = (gm_diffs.square().sum(dim=-1, keepdim=True)
                        * (-0.5 * power_ratio / norm_factor))
    out_logweights = (logweights + logweights_delta).log_softmax(dim=1)

    out_logstds = logstds + g_logstd.unsqueeze(-1) - 0.5 * torch.log(norm_factor)

    return dict(means=out_means, logstds=out_logstds, logweights=out_logweights), gm_power""")

# ===================================================================
# 4. gm_logprob
# ===================================================================
code = _replace_body(code, "gm_logprob", """\
    means = gm['means']
    logstds = gm['logstds']
    logweights = gm['logweights']

    bs, K, D = means.shape
    const = -0.5 * D * math.log(2.0 * math.pi)

    diff = samples.unsqueeze(2) - means.unsqueeze(1)
    inv_std = torch.exp(-logstds).unsqueeze(1)
    diff_scaled = diff * inv_std

    gaussian_logprobs = (-0.5 * diff_scaled.square().sum(dim=-1)
                         - D * logstds.squeeze(-1).unsqueeze(1)
                         + const)

    lw = logweights.squeeze(-1).unsqueeze(1)
    logprob = torch.logsumexp(lw + gaussian_logprobs, dim=-1)

    return logprob, gaussian_logprobs""")

# ===================================================================
# 5. gm_logpdf_c
# ===================================================================
code = _replace_body(code, "gm_logpdf_c", """\
    lib_path = "/app/libgm_logpdf.so"
    lib = ctypes.CDLL(lib_path)
    lib.gm_logpdf_batch.restype = None
    lib.gm_logpdf_batch.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
        ctypes.c_double,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]

    N, D = samples_np.shape
    K = means_np.shape[0]

    samples_c = np.ascontiguousarray(samples_np, dtype=np.float64)
    means_c = np.ascontiguousarray(means_np, dtype=np.float64)
    lw_c = np.ascontiguousarray(logweights_np, dtype=np.float64)
    output = np.zeros(N, dtype=np.float64)

    lib.gm_logpdf_batch(
        N, K, D,
        samples_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        means_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_double(float(logstd)),
        lw_c.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        output.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
    )

    return output""")

# ===================================================================
# 6. gm_kl_div
# ===================================================================
code = _replace_body(code, "gm_kl_div", """\
    samples = gm_to_sample(gm_p, n_samples)
    logp = gm_logprob(gm_p, samples)[0]
    logq = gm_logprob(gm_q, samples)[0]
    return (logp - logq).mean(dim=-1)""")

# ------------------------------------------------------------------ write
with open(SRC, "w") as f:
    f.write(code)

print("All Python function stubs implemented.")

# =====================================================================
# Complete and compile the C extension
# =====================================================================

C_CODE = r"""/*
 * Batch Gaussian Mixture log-PDF computation with numerical stability.
 *
 * Compile:  gcc -shared -fPIC -O2 -o libgm_logpdf.so gm_logpdf.c -lm
 *
 */

#include <math.h>
#include <stdlib.h>
#include <float.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

void gm_logpdf_batch(
    int N, int K, int D,
    const double *samples,
    const double *means,
    double logstd,
    const double *logweights,
    double *output
) {
    int n, k, d;
    double const_term = -0.5 * D * log(2.0 * M_PI);
    double inv_std = exp(-logstd);

    double *terms = (double *)malloc(K * sizeof(double));
    if (!terms) return;

    for (n = 0; n < N; n++) {
        double max_val = -DBL_MAX;

        for (k = 0; k < K; k++) {
            double sq_sum = 0.0;
            for (d = 0; d < D; d++) {
                double diff = (samples[n * D + d] - means[k * D + d]) * inv_std;
                sq_sum += diff * diff;
            }
            terms[k] = logweights[k]
                      + (-0.5 * sq_sum - D * logstd + const_term);
            if (terms[k] > max_val) max_val = terms[k];
        }

        double sum = 0.0;
        for (k = 0; k < K; k++) {
            sum += exp(terms[k] - max_val);
        }
        output[n] = max_val + log(sum);
    }

    free(terms);
}
"""

with open("/app/gm_logpdf.c", "w") as f:
    f.write(C_CODE)

print("Wrote complete C extension to gm_logpdf.c")

result = subprocess.run(
    ["gcc", "-shared", "-fPIC", "-O2",
     "-o", "/app/libgm_logpdf.so", "/app/gm_logpdf.c", "-lm"],
    capture_output=True, text=True,
)

if result.returncode != 0:
    print(f"gcc FAILED:\n{result.stderr}")
    raise RuntimeError("C compilation failed")

print("Compiled libgm_logpdf.so successfully")
