"""
Reference implementation of Raven hydrological diagnostic metrics.
Faithfully replicates the C++ implementation in Diagnostics.cpp.
This module serves as the test oracle.
"""


import math
from datetime import datetime, timedelta

ALMOST_INF = 1e32


def compute_baseweights(observed, modeled, weights, blank_value, threshold, comparison):
    """Compute base weights following C++ logic in CalculateDiagnostic."""
    n = len(observed)
    baseweight = list(weights) if weights else [1.0] * n

    # Collect non-blank obs for threshold computation
    allvals = []
    for i in range(n):
        if observed[i] != blank_value:
            allvals.append(observed[i])
    Nobs = len(allvals)

    thresh_obsval = 0.0
    if Nobs > 1 and comparison != "NONE":
        corr = 0
        if comparison == "LESSTHAN":
            corr = -1
        allvals.sort()
        idx = int(math.floor(threshold * Nobs)) + corr
        idx = max(0, min(idx, Nobs - 1))
        thresh_obsval = allvals[idx]

    # Apply blank masking and threshold filtering
    for i in range(n):
        if observed[i] == blank_value:
            baseweight[i] = 0.0
        if modeled[i] == blank_value:
            baseweight[i] = 0.0
        if comparison == "GREATERTHAN":
            if observed[i] < thresh_obsval:
                baseweight[i] = 0.0
        elif comparison == "LESSTHAN":
            if observed[i] > thresh_obsval:
                baseweight[i] = 0.0

    return baseweight


def _get_month(nn, start_date_str, timestep):
    """Convert timestep index to month number (1-12)."""
    start = datetime.strptime(start_date_str, "%Y-%m-%d")
    date = start + timedelta(days=nn * timestep)
    return date.month


def _get_ranks(values, n):
    """Assign 0-based ordinal ranks to n values (replicates C++ getRanks)."""
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0] * n
    for rank_val, idx in enumerate(indexed):
        ranks[idx] = rank_val
    return ranks


def diag_nash_sutcliffe(obs, mod, bw, s, e):
    avgobs = 0.0
    N = 0.0
    for nn in range(s, e):
        avgobs += bw[nn] * obs[nn]
        N += bw[nn]
    if N > 0:
        avgobs /= N
    sum1 = sum2 = 0.0
    for nn in range(s, e):
        sum1 += bw[nn] * (obs[nn] - mod[nn]) ** 2
        sum2 += bw[nn] * (obs[nn] - avgobs) ** 2
    if N > 0 and sum2 != 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_daily_nse(obs, mod, bw, s, e, timestep):
    """For daily timestep (freq=1), equivalent to regular NSE."""
    freq = int(round(1.0 / timestep))
    shift = 0  # For daily timestep, shift is always 0
    avgobs = 0.0
    N = 0.0
    for nn in range(s + shift, e):
        avgobs += bw[nn] * obs[nn]
        N += bw[nn]
    if N > 0:
        avgobs /= N
    sum1 = sum2 = 0.0
    obsdaily = moddaily = dailyN = 0.0
    for nn in range(s + shift, e):
        w = bw[nn]
        obsdaily += w * obs[nn]
        moddaily += w * mod[nn]
        dailyN += w
        if ((nn - (s + shift)) % freq) == (freq - 1):
            if dailyN > 0:
                obsdaily /= dailyN
                moddaily /= dailyN
                sum1 += (obsdaily - moddaily) ** 2 * w
                sum2 += (obsdaily - avgobs) ** 2 * w
            dailyN = obsdaily = moddaily = 0.0
    if N > 0 and sum2 != 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_nash_sutcliffe_der(obs, mod, bw, s, e, dt):
    e2 = e - 1
    avg = 0.0
    N = 0.0
    for nn in range(s, e2):
        w = bw[nn + 1] * bw[nn]
        avg += w * (obs[nn + 1] - obs[nn]) / dt
        N += w
    if N > 0:
        avg /= N
    sum1 = sum2 = 0.0
    for nn in range(s, e2):
        w = bw[nn + 1] * bw[nn]
        obs_der = (obs[nn + 1] - obs[nn]) / dt
        mod_der = (mod[nn + 1] - mod[nn]) / dt
        sum1 += w * (obs_der - mod_der) ** 2
        sum2 += w * (obs_der - avg) ** 2
    if N > 0 and sum2 != 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_nash_sutcliffe_run(obs, mod, bw, s, e, width):
    if width < 2:
        return -ALMOST_INF
    if width * 2 > e:
        return -ALMOST_INF
    e2 = e - width
    s2 = s + width
    front = width // 2
    if width % 2 == 1:
        back = front
    else:
        back = front - 1
    # First pass: compute weighted mean of window-averaged obs
    avg = 0.0
    N = 0.0
    for nn in range(s2, e2):
        obsavg = 0.0
        w = bw[nn]
        for k in range(nn - front, nn + back + 1):
            obsavg += obs[k]
            w *= bw[k]
        obsval = obsavg / width
        avg += obsval * w
        N += w
    if N > 0:
        avg /= N
    # Second pass: compute NSE
    sum1 = sum2 = 0.0
    for nn in range(s2, e2):
        modavg = obsavg = 0.0
        w = bw[nn]
        for k in range(nn - front, nn + back + 1):
            modavg += mod[k]
            obsavg += obs[k]
            w *= bw[k]
        modval = modavg / width
        obsval = obsavg / width
        sum1 += (obsval - modval) ** 2 * w
        sum2 += (obsval - avg) ** 2 * w
    if N > 0 and sum2 != 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_log_nash(obs, mod, bw, s, e, blank_value):
    avg = 0.0
    N = 0.0
    for nn in range(s, e):
        obsval = obs[nn]
        modval = mod[nn]
        w = bw[nn]
        if obsval <= 0.0 or obsval == blank_value:
            obsval = blank_value
        else:
            obsval = math.log(obsval)
        if modval <= 0.0 or obsval == blank_value:
            modval = blank_value
        else:
            modval = math.log(modval)
        if obsval == blank_value:
            w = 0.0
        if modval == blank_value:
            w = 0.0
        avg += obsval * w
        N += w
    if N > 0:
        avg /= N
    sum1 = sum2 = 0.0
    for nn in range(s, e):
        obsval = obs[nn]
        modval = mod[nn]
        w = bw[nn]
        if obsval <= 0.0 or obsval == blank_value:
            obsval = blank_value
        else:
            obsval = math.log(obsval)
        if modval <= 0.0 or obsval == blank_value:
            modval = blank_value
        else:
            modval = math.log(modval)
        if obsval == blank_value:
            w = 0.0
        if modval == blank_value:
            w = 0.0
        sum1 += (obsval - modval) ** 2 * w
        sum2 += (obsval - avg) ** 2 * w
    if N > 0 and sum2 != 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_nse4(obs, mod, bw, s, e):
    avgobs = 0.0
    N = 0.0
    for nn in range(s, e):
        avgobs += bw[nn] * obs[nn]
        N += bw[nn]
    if N > 0:
        avgobs /= N
    sum1 = sum2 = 0.0
    for nn in range(s, e):
        sum1 += bw[nn] * (obs[nn] - mod[nn]) ** 4
        sum2 += bw[nn] * (obs[nn] - avgobs) ** 4
    if N > 0 and sum2 != 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_fuzzy_nash(obs, mod, bw, s, e, width):
    avgobs = 0.0
    N = 0.0
    # C++ integer division: _width/100 where both are int
    pct = width // 100
    for nn in range(s, e):
        avgobs += bw[nn] * obs[nn]
        N += bw[nn]
    if N > 0:
        avgobs /= N
    sum1 = sum2 = 0.0
    for nn in range(s, e):
        w = bw[nn]
        obsval = obs[nn]
        modval = mod[nn]
        eps = max(modval - obsval * (1.0 + pct), 0.0) + max(obsval * (1.0 - pct) - modval, 0.0)
        eps2 = max(avgobs - obsval * (1.0 + pct), 0.0) + max(avgobs * (1.0 - pct) - modval, 0.0)
        sum1 += w * eps ** 2
        sum2 += w * eps2 ** 2
    if N > 0 and sum2 > 0:
        return 1.0 - sum1 / sum2
    return -ALMOST_INF


def diag_rmse(obs, mod, bw, s, e):
    total = 0.0
    N = 0.0
    for nn in range(s, e):
        total += bw[nn] * (obs[nn] - mod[nn]) ** 2
        N += bw[nn]
    if N > 0:
        return math.sqrt(total / N)
    return -ALMOST_INF


def diag_rmse_der(obs, mod, bw, s, e, dt):
    total = 0.0
    N = 0.0
    for nn in range(s, e - 1):
        w = bw[nn] * bw[nn + 1]
        obsval = (obs[nn + 1] - obs[nn]) / dt
        modval = (mod[nn + 1] - mod[nn]) / dt
        total += w * (obsval - modval) ** 2
        N += w
    if N > 0:
        return math.sqrt(total / N)
    return -ALMOST_INF


def diag_kling_gupta(obs, mod, bw, s, e, metric_type="KLING_GUPTA"):
    ObsSum = ModSum = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        ObsSum += obs[nn] * w
        ModSum += mod[nn] * w
        N += w
    if N <= 0:
        return -ALMOST_INF
    ObsAvg = ObsSum / N
    ModAvg = ModSum / N
    ObsStd = ModStd = Cov = 0.0
    for nn in range(s, e):
        w = bw[nn]
        ObsStd += (obs[nn] - ObsAvg) ** 2 * w
        ModStd += (mod[nn] - ModAvg) ** 2 * w
        Cov += (obs[nn] - ObsAvg) * (mod[nn] - ModAvg) * w
    ObsStd = math.sqrt(ObsStd / N)
    ModStd = math.sqrt(ModStd / N)
    Cov /= N
    r = Cov / ObsStd / ModStd
    Beta = ModAvg / ObsAvg
    Alpha = ModStd / ObsStd
    if metric_type == "KLING_GUPTA_DEVIATION":
        Beta = 1.0
    if metric_type == "KGE_PRIME":
        if Beta != 0.0:
            Alpha /= Beta
    if (N > 0) and ((ObsAvg != 0.0) or (Beta == 1.0)) and (ObsStd != 0.0) and (ModStd != 0.0):
        return 1.0 - math.sqrt((r - 1) ** 2 + (Alpha - 1) ** 2 + (Beta - 1) ** 2)
    return -ALMOST_INF


def diag_kling_gupta_der(obs, mod, bw, s, e, dt):
    e2 = e - 1
    ObsSum = ModSum = 0.0
    N = 0.0
    for nn in range(s, e2):
        w = bw[nn] * bw[nn + 1]
        obsval = (obs[nn + 1] - obs[nn]) / dt
        modval = (mod[nn + 1] - mod[nn]) / dt
        ObsSum += obsval * w
        ModSum += modval * w
        N += w
    if N <= 0:
        return -ALMOST_INF
    ObsAvg = ObsSum / N
    ModAvg = ModSum / N
    ObsStd = ModStd = Cov = 0.0
    for nn in range(s, e2):
        w = bw[nn] * bw[nn + 1]
        obsval = (obs[nn + 1] - obs[nn]) / dt
        modval = (mod[nn + 1] - mod[nn]) / dt
        ObsStd += (obsval - ObsAvg) ** 2 * w
        ModStd += (modval - ModAvg) ** 2 * w
        Cov += (obsval - ObsAvg) * (modval - ModAvg) * w
    ObsStd = math.sqrt(ObsStd / N)
    ModStd = math.sqrt(ModStd / N)
    Cov /= N
    r = Cov / ObsStd / ModStd
    Beta = ModAvg / ObsAvg
    Alpha = ModStd / ObsStd
    if (N > 0) and (ObsAvg != 0.0) and (ObsStd != 0.0) and (ModStd != 0.0):
        return 1.0 - math.sqrt((r - 1) ** 2 + (Alpha - 1) ** 2 + (Beta - 1) ** 2)
    return -ALMOST_INF


def diag_daily_kge(obs, mod, bw, s, e, timestep):
    freq = int(round(1.0 / timestep))
    shift = 0
    avgobs = avgmod = 0.0
    N = 0.0
    for nn in range(s + shift, e):
        w = bw[nn]
        avgobs += w * obs[nn]
        avgmod += w * mod[nn]
        N += w
    if N > 0:
        avgobs /= N
        avgmod /= N
    obsstd = modstd = covar = 0.0
    obsdaily = moddaily = dailyN = 0.0
    for nn in range(s + shift, e):
        w = bw[nn]
        obsdaily += w * obs[nn]
        moddaily += w * mod[nn]
        dailyN += w
        if ((nn - (s + shift)) % freq) == (freq - 1):
            if dailyN > 0:
                obsdaily /= dailyN
                moddaily /= dailyN
                obsstd += w * (obsdaily - avgobs) ** 2
                modstd += w * (moddaily - avgmod) ** 2
                covar += w * (obsdaily - avgobs) * (moddaily - avgmod)
            dailyN = obsdaily = moddaily = 0.0
    if N > 0:
        obsstd = math.sqrt(obsstd / N)
        modstd = math.sqrt(modstd / N)
        covar /= N
    if obsstd == 0 or modstd == 0 or avgobs == 0:
        return -ALMOST_INF
    r = covar / obsstd / modstd
    beta = avgmod / avgobs
    alpha = modstd / obsstd
    if N > 0:
        return 1.0 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return -ALMOST_INF


def diag_pct_bias(obs, mod, bw, s, e):
    sum1 = sum2 = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        sum1 += w * (mod[nn] - obs[nn])
        sum2 += w * obs[nn]
        N += w
    if N > 0:
        return 100.0 * sum1 / sum2
    return ALMOST_INF


def diag_abs_pct_bias(obs, mod, bw, s, e):
    sum1 = sum2 = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        sum1 += w * (mod[nn] - obs[nn])
        sum2 += w * obs[nn]
        N += w
    if N > 0:
        return abs(100.0 * sum1 / sum2)
    return ALMOST_INF


def diag_abserr(obs, mod, bw, s, e):
    total = 0.0
    N = 0.0
    for nn in range(s, e):
        total += bw[nn] * abs(obs[nn] - mod[nn])
        N += bw[nn]
    if N > 0:
        return total / N
    return -ALMOST_INF


def diag_abserr_run(obs, mod, bw, s, e, width):
    if width < 2:
        return -ALMOST_INF
    if width * 2 > e:
        return -ALMOST_INF
    e2 = e - width
    s2 = s + width
    front = width // 2
    if width % 2 == 1:
        back = front
    else:
        back = front - 1
    N = 0.0
    sum1 = 0.0
    for nn in range(s2, e2):
        modavg = obsavg = 0.0
        w = bw[nn]
        for k in range(nn - front, nn + back + 1):
            modavg += mod[k]
            obsavg += obs[k]
            w *= bw[k]
        N += w
        modval = modavg / width
        obsval = obsavg / width
        sum1 += abs(obsval - modval) * w
    if N > 0:
        return sum1  # Note: NOT divided by N, matching C++ code
    return -ALMOST_INF


def diag_absmax(obs, mod, bw, s, e):
    maxerr = -ALMOST_INF
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        if w > 0:
            err = abs(obs[nn] - mod[nn])
            if err > maxerr:
                maxerr = err
            N += w
    if N > 0:
        return maxerr
    return -ALMOST_INF


def diag_pdiff(obs, mod, bw, s, e):
    maxObs = maxMod = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        if w > 0:
            if obs[nn] > maxObs:
                maxObs = obs[nn]
            if mod[nn] > maxMod:
                maxMod = mod[nn]
            N += w
    if N > 0:
        return maxMod - maxObs
    return -ALMOST_INF


def diag_pct_pdiff(obs, mod, bw, s, e):
    maxObs = maxMod = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        if w > 0:
            if obs[nn] > maxObs:
                maxObs = obs[nn]
            if mod[nn] > maxMod:
                maxMod = mod[nn]
            N += w
    if N > 0 and maxObs != 0:
        return 100.0 * (maxMod - maxObs) / maxObs
    return -ALMOST_INF


def diag_abs_pct_pdiff(obs, mod, bw, s, e):
    maxObs = maxMod = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        if w > 0:
            if obs[nn] > maxObs:
                maxObs = obs[nn]
            if mod[nn] > maxMod:
                maxMod = mod[nn]
            N += w
    if N > 0 and maxObs != 0:
        return abs(100.0 * (maxMod - maxObs) / maxObs)
    return -ALMOST_INF


def diag_tmvol(obs, mod, bw, s, e, start_date, timestep):
    mon = 1
    n_days = 0.0
    tmvol = 0.0
    tempsum = 0.0
    N = 0.0
    # Find month of first valid entry
    for nn in range(s, e):
        if bw[nn] != 0:
            mon = _get_month(nn, start_date, timestep)
            break
    for nn in range(s, e):
        w = bw[nn]
        if w != 0:
            m = _get_month(nn, start_date, timestep)
            if m != mon:
                mon = m
                if n_days > 0:
                    tmvol += (tempsum / n_days) ** 2
                n_days = 0.0
                tempsum = 0.0
            tempsum += (mod[nn] - obs[nn]) * w
            n_days += w
        N += w
    # Final month
    if n_days > 0:
        tmvol += (tempsum / n_days) ** 2
    if N > 0:
        return tmvol
    return -ALMOST_INF


def diag_tmvol_mare(obs, mod, bw, s, e, start_date, timestep):
    mon = 1
    tmvol_abs = 0.0
    tempsum = 0.0
    obs_sum = 0.0
    m_count = 0
    N = 0.0
    for nn in range(s, e):
        if bw[nn] != 0:
            mon = _get_month(nn, start_date, timestep)
            break
    for nn in range(s, e):
        w = bw[nn]
        if w != 0:
            m = _get_month(nn, start_date, timestep)
            if m != mon:
                if obs_sum > 0:
                    tmvol_abs += abs(tempsum / obs_sum) * 100.0
                    m_count += 1
                mon = m
                tempsum = 0.0
                obs_sum = 0.0
            tempsum += (mod[nn] - obs[nn]) * w
            obs_sum += obs[nn] * w
        N += w
    if obs_sum > 0:
        tmvol_abs += abs(tempsum / obs_sum) * 100.0
        m_count += 1
    if m_count > 0:
        return tmvol_abs / m_count
    return -ALMOST_INF


def diag_rcoef(obs, mod, bw, s, e):
    N = 0.0
    ModSum = ObsSum = 0.0
    for nn in range(s, e - 1):
        w = bw[nn] * bw[nn + 1]
        ModSum += w * mod[nn]
        ObsSum += w * obs[nn]
        N += w
    if N <= 0:
        return -ALMOST_INF
    ModAvg = ModSum / N
    ObsAvg = ObsSum / N
    TopSum = ModDiffSum = ObsDiffSum = 0.0
    for nn in range(s, e - 1):
        w = bw[nn] * bw[nn + 1]
        TopSum += w * (mod[nn + 1] - obs[nn + 1]) * (mod[nn] - obs[nn])
        ModDiffSum += w * (mod[nn] - ModAvg) ** 2
        ObsDiffSum += w * (obs[nn] - ObsAvg) ** 2
    modstd = math.sqrt(ModDiffSum / N)
    obsstd = math.sqrt(ObsDiffSum / N)
    if N > 0 and obsstd != 0 and modstd != 0:
        return TopSum / N / (modstd * obsstd)
    return -ALMOST_INF


def diag_nsc(obs, mod, bw, s, e):
    nsc = 0.0
    N = 0.0
    for nn in range(s, e - 1):
        w = bw[nn] * bw[nn + 1]
        if w > 0:
            val1 = math.ceil((obs[nn] - mod[nn]) * 1000) / 1000
            val2 = math.ceil((obs[nn + 1] - mod[nn + 1]) * 1000) / 1000
            if val1 * val2 < 0:
                nsc += 1
        N += w
    if N > 0:
        return nsc
    return ALMOST_INF


def diag_rsr(obs, mod, bw, s, e):
    ObsSum = 0.0
    N = 0.0
    for nn in range(s, e):
        ObsSum += obs[nn] * bw[nn]
        N += bw[nn]
    if N <= 0:
        return -ALMOST_INF
    ObsAvg = ObsSum / N
    TopSum = BotSum = 0.0
    for nn in range(s, e):
        w = bw[nn]
        TopSum += (obs[nn] - mod[nn]) ** 2 * w
        BotSum += (obs[nn] - ObsAvg) ** 2 * w
    if N > 0 and BotSum != 0 and ObsSum != 0:
        return math.sqrt(TopSum / BotSum)
    return -ALMOST_INF


def diag_r2(obs, mod, bw, s, e):
    ObsSum = ModSum = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        ObsSum += obs[nn] * w
        ModSum += mod[nn] * w
        N += w
    if N <= 0:
        return -ALMOST_INF
    ObsAvg = ObsSum / N
    ModAvg = ModSum / N
    CovXY = CovXX = CovYY = 0.0
    for nn in range(s, e):
        w = bw[nn]
        CovXY += w * (mod[nn] - ModAvg) * (obs[nn] - ObsAvg)
        CovXX += w * (mod[nn] - ModAvg) ** 2
        CovYY += w * (obs[nn] - ObsAvg) ** 2
    CovXY /= N
    CovXX /= N
    CovYY /= N
    if N > 0 and CovXX != 0 and CovYY != 0:
        return CovXY ** 2 / (CovXX * CovYY)
    return -ALMOST_INF


def diag_mbf(obs, mod, bw, s, e):
    total = 0.0
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        total += w / (1.0 + ((mod[nn] - obs[nn]) / (2.0 * obs[nn])) ** 2)
        N += w
    if N > 0:
        return total
    return -ALMOST_INF


def diag_r4ms4e(obs, mod, bw, s, e):
    total = 0.0
    N = 0.0
    for nn in range(s, e):
        total += bw[nn] * (obs[nn] - mod[nn]) ** 4
        N += bw[nn]
    if N > 0:
        return (total / N) ** 0.25
    return -ALMOST_INF


def diag_rtrmse(obs, mod, bw, s, e):
    total = 0.0
    N = 0.0
    for nn in range(s, e):
        total += bw[nn] * (math.sqrt(obs[nn]) - math.sqrt(mod[nn])) ** 2
        N += bw[nn]
    if N > 0:
        return math.sqrt(total / N)
    return -ALMOST_INF


def diag_rabserr(obs, mod, bw, s, e):
    avgobs = 0.0
    N = 0.0
    for nn in range(s, e):
        avgobs += bw[nn] * obs[nn]
        N += bw[nn]
    if N > 0:
        avgobs /= N
    sum1 = sum2 = 0.0
    for nn in range(s, e):
        w = bw[nn]
        sum1 += w * abs(obs[nn] - mod[nn])
        sum2 += w * abs(avgobs - mod[nn])  # Note: avgobs-mod, NOT avgobs-obs
    if N > 0 and sum2 != 0:
        return sum1 / sum2
    return -ALMOST_INF


def diag_persindex(obs, mod, bw, s, e):
    sum1 = sum2 = 0.0
    N = 0.0
    for nn in range(s + 1, e):
        prvmod = mod[nn - 1]
        w = bw[nn] * bw[nn - 1]
        sum1 += w * (mod[nn] - obs[nn]) ** 2
        sum2 += w * (mod[nn] - prvmod) ** 2
        N += w
    if N > 0 and sum2 != 0:
        return 1 - sum1 / sum2
    return -ALMOST_INF


def diag_years_of_record(obs, mod, bw, s, e, timestep):
    N = 0.0
    for nn in range(s, e):
        w = bw[nn]
        if w > 0:
            w = 1.0
        N += w
    return N / 365 / timestep


def diag_spearman(obs, mod, bw, s, e, blank_value):
    mvals = []
    ovals = []
    for nn in range(s, e):
        if obs[nn] != blank_value and bw[nn] > 0:
            ovals.append(obs[nn])
            mvals.append(mod[nn])
    N = len(ovals)
    if N > 1:
        rank1 = _get_ranks(mvals, N)
        rank2 = _get_ranks(ovals, N)
        mean1 = mean2 = 0.0
        for n in range(N):
            mean1 += rank1[n] / N
            mean2 += rank2[n] / N
        std1 = std2 = cov = 0.0
        for n in range(N):
            std1 += (rank1[n] - mean1) ** 2 / N
            std2 += (rank2[n] - mean2) ** 2 / N
            cov += (rank1[n] - mean1) * (rank2[n] - mean2) / N
        if std1 > 0 and std2 > 0:
            spearman = cov / math.sqrt(std1) / math.sqrt(std2)
        else:
            spearman = 0
    elif N > 0:
        spearman = 0
    else:
        return -ALMOST_INF
    return spearman


def compute_metric(name, width, obs, mod, bw, s, e, dt, start_date, blank_value=-1.2345):
    """Dispatch to the appropriate metric function."""
    if name == "NASH_SUTCLIFFE":
        return diag_nash_sutcliffe(obs, mod, bw, s, e)
    elif name == "DAILY_NSE":
        return diag_daily_nse(obs, mod, bw, s, e, dt)
    elif name == "NASH_SUTCLIFFE_DER":
        return diag_nash_sutcliffe_der(obs, mod, bw, s, e, dt)
    elif name == "NASH_SUTCLIFFE_RUN":
        return diag_nash_sutcliffe_run(obs, mod, bw, s, e, width)
    elif name == "LOG_NASH":
        return diag_log_nash(obs, mod, bw, s, e, blank_value)
    elif name == "NSE4":
        return diag_nse4(obs, mod, bw, s, e)
    elif name == "FUZZY_NASH":
        return diag_fuzzy_nash(obs, mod, bw, s, e, width)
    elif name == "RMSE":
        return diag_rmse(obs, mod, bw, s, e)
    elif name == "RMSE_DER":
        return diag_rmse_der(obs, mod, bw, s, e, dt)
    elif name == "KLING_GUPTA":
        return diag_kling_gupta(obs, mod, bw, s, e, "KLING_GUPTA")
    elif name == "KGE_PRIME":
        return diag_kling_gupta(obs, mod, bw, s, e, "KGE_PRIME")
    elif name == "KLING_GUPTA_DEVIATION":
        return diag_kling_gupta(obs, mod, bw, s, e, "KLING_GUPTA_DEVIATION")
    elif name == "KLING_GUPTA_DER":
        return diag_kling_gupta_der(obs, mod, bw, s, e, dt)
    elif name == "DAILY_KGE":
        return diag_daily_kge(obs, mod, bw, s, e, dt)
    elif name == "PCT_BIAS":
        return diag_pct_bias(obs, mod, bw, s, e)
    elif name == "ABS_PCT_BIAS":
        return diag_abs_pct_bias(obs, mod, bw, s, e)
    elif name == "ABSERR":
        return diag_abserr(obs, mod, bw, s, e)
    elif name == "ABSERR_RUN":
        return diag_abserr_run(obs, mod, bw, s, e, width)
    elif name == "ABSMAX":
        return diag_absmax(obs, mod, bw, s, e)
    elif name == "PDIFF":
        return diag_pdiff(obs, mod, bw, s, e)
    elif name == "PCT_PDIFF":
        return diag_pct_pdiff(obs, mod, bw, s, e)
    elif name == "ABS_PCT_PDIFF":
        return diag_abs_pct_pdiff(obs, mod, bw, s, e)
    elif name == "TMVOL":
        return diag_tmvol(obs, mod, bw, s, e, start_date, dt)
    elif name == "TMVOL_MARE":
        return diag_tmvol_mare(obs, mod, bw, s, e, start_date, dt)
    elif name == "RCOEF":
        return diag_rcoef(obs, mod, bw, s, e)
    elif name == "NSC":
        return diag_nsc(obs, mod, bw, s, e)
    elif name == "RSR":
        return diag_rsr(obs, mod, bw, s, e)
    elif name == "R2":
        return diag_r2(obs, mod, bw, s, e)
    elif name == "MBF":
        return diag_mbf(obs, mod, bw, s, e)
    elif name == "R4MS4E":
        return diag_r4ms4e(obs, mod, bw, s, e)
    elif name == "RTRMSE":
        return diag_rtrmse(obs, mod, bw, s, e)
    elif name == "RABSERR":
        return diag_rabserr(obs, mod, bw, s, e)
    elif name == "PERSINDEX":
        return diag_persindex(obs, mod, bw, s, e)
    elif name == "YEARS_OF_RECORD":
        return diag_years_of_record(obs, mod, bw, s, e, dt)
    elif name == "SPEARMAN":
        return diag_spearman(obs, mod, bw, s, e, blank_value)
    else:
        raise ValueError(f"Unknown metric: {name}")
