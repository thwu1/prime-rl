# Log-price objective for Halley iteration
# Uses erfcx for numerical stability in deep OTM regime
# Reference fragment

function normalizePrice(isCall, price, f, strike, df)
    c = price / f / df
    ex = f / strike
    if !isCall
        if ex <= 1
            c = c + 1 - 1 / ex  # put-call parity
        else
            c = ex * c           # in-out duality + put-call parity
            ex = 1 / ex
        end
    else
        if ex > 1
            c = (f * (c - 1) + strike) / strike  # in-out duality
            ex = 1 / ex
        end
    end
    return c, ex
end

function objectiveLog(x, ex, v, logc)
    v = abs(v)
    h = x / v
    t = v / 2
    sqrt2 = sqrt(2.0)
    Np = erfcx(-(h + t) / sqrt2)
    Nm = erfcx(-(h - t) / sqrt2)
    eh2t2 = exp(-(h * h + t * t) / 2)
    norm = 1 / (2 * sqrt(ex)) * eh2t2
    cEstimate = norm * (Np - Nm)
    logcEstimate = log(cEstimate)
    logvega = (2 / sqrt(2 * pi)) / (Np - Nm)
    volgaOverVega = (h + t) * (h - t) / v
    logvolgaOverVega = volgaOverVega - logvega
    return logcEstimate - logc, (logcEstimate - logc) / logvega, logvolgaOverVega
end

# Halley step: delta_v = -(1 / (1 - lf/2)) * fb_over_fpb
# where lf = fb_over_fpb * fp2b_over_fpb
# Converges cubically (3rd order) when log-price objective is used
