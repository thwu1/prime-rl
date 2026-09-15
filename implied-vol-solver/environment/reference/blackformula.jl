# Black-Scholes formula and related functions
# Reference implementation fragment

using SpecialFunctions: erfcx

const SqrtEpsilon = sqrt(eps())

function normcdf(z::T)::T where {T}
    return erfc(-z / sqrt(T(2))) / 2
end

function normpdf(z::T)::T where {T}
    return exp(-z * z / 2) / sqrt(2 * T(pi))
end

function blackScholesFormula(isCall, strike, spot, totalVariance, driftDf, discountDf)
    sign = isCall ? 1 : -1
    forward = spot / driftDf
    if totalVariance < eps()
        return discountDf * max(sign * (forward - strike), 0)
    end
    sqrtVar = sqrt(totalVariance)
    d1 = log(forward / strike) / sqrtVar + sqrtVar / 2
    d2 = d1 - sqrtVar
    return sign * discountDf * (forward * normcdf(sign * d1) - strike * normcdf(sign * d2))
end

function blackScholesVega(strike, spot, totalVariance, driftDf, discountDf, tte)
    forward = spot / driftDf
    sqrtVar = sqrt(totalVariance)
    d1 = log(forward / strike) / sqrtVar + sqrtVar / 2
    vega = discountDf * forward * normpdf(d1) * sqrt(tte)
    return vega
end
