"""Dimension-scaling analysis for algorithm runtimes."""


def compute_scaling(ert_results, algorithms, functions, dimensions):
    """Estimate how ERT scales with problem dimension.

    Fits a linear model  ERT = a + b * dim  via ordinary least squares.
    Reports the slope b for each (algorithm, function) pair.
    Only dimensions where ERT at the tightest target is finite are used.
    """
    results = {}
    for algo in algorithms:
        for func in functions:
            x_vals = []
            y_vals = []
            for dim in dimensions:
                key = f"{algo}_f{func}_d{dim}_t1e-08"
                ert_val = ert_results.get(key)
                if ert_val is not None:
                    x_vals.append(float(dim))
                    y_vals.append(float(ert_val))

            skey = f"{algo}_f{func}"
            if len(x_vals) < 2:
                results[skey] = None
            else:
                n = len(x_vals)
                x_mean = sum(x_vals) / n
                y_mean = sum(y_vals) / n
                num = sum((x - x_mean) * (y - y_mean)
                          for x, y in zip(x_vals, y_vals))
                den = sum((x - x_mean) ** 2 for x in x_vals)
                if den == 0:
                    results[skey] = None
                else:
                    results[skey] = num / den
    return results
