# Sovereign Debt Dynamics - Technical Reference

## Overview

This document describes the accounting framework for analyzing the evolution of public debt-to-GDP ratios. The framework enables projection of future debt ratios given macroeconomic assumptions, decomposition of debt changes into contributing factors, and assessment of financing vulnerabilities.

**Conventions:** All flow variables are expressed as shares of GDP. The primary balance is signed surplus-positive (a positive primary balance indicates a fiscal surplus, reducing debt). Rates (interest, growth, inflation) are expressed as decimals (e.g., 0.02 = 2%). Debt ratios are expressed in percentage points of GDP (e.g., 65.0 = 65% of GDP).

## Notation

| Symbol | Description |
|--------|-------------|
| d_t | Total public debt-to-GDP ratio at end of period t |
| d^f_t | Foreign-currency debt-to-GDP ratio |
| alpha | Constant share of total debt denominated in foreign currency: d^f_t = alpha * d_t |
| g_t | Real GDP growth rate |
| pi^d_t | Domestic inflation (GDP deflator growth rate) |
| pi^f_t | Foreign inflation |
| i_t | Nominal effective interest rate on public debt |
| r_t | Real effective interest rate: r_t = (1 + i_t)/(1 + pi^d_t) - 1 |
| z_t | Real exchange rate depreciation (positive = depreciation of domestic currency) |
| pb_t | Primary balance (surplus-positive) as a share of GDP |
| sfa_t | Stock-flow adjustment as a share of GDP |
| rho_t | Nominal GDP growth factor: rho_t = (1 + g_t)(1 + pi^d_t) |

## Debt Accumulation Identity

The change in the debt-to-GDP ratio from period t-1 to period t decomposes as:

    delta_d_t = [(r_t - g_t) / (1 + g_t)] * d_{t-1}
              + [z_t * d^f_{t-1}] / [(1 + g_t)(1 + pi^f_t)]
              + [(pi^d_t - pi^f_t) / ((1 + pi^f_t) * rho_t)] * d^f_{t-1}
              - pb_t
              + sfa_t

The first term captures the **interest rate-growth differential**: the autonomous tendency of debt to rise when the cost of servicing it exceeds economic growth. This differential operates on the entire debt stock d_{t-1}, not merely the domestic-currency portion.

The second term captures the **real exchange rate channel**: real depreciation of the domestic currency (z > 0) increases the GDP-value of foreign-currency obligations.

The third term captures the **relative inflation channel**: when domestic inflation exceeds foreign inflation, it affects the real burden of foreign-currency debt relative to GDP through the nominal GDP deflator.

The primary balance enters with a negative sign because a surplus (pb > 0) reduces debt. Stock-flow adjustments capture items that affect the debt stock but not the deficit (privatization proceeds, asset purchases, valuation changes not captured elsewhere).

### Interest-Growth Differential Decomposition

The interest-growth differential term [(r - g)/(1 + g)] * d can be equivalently written as:

    [r/(1 + g)] * d - [g/(1 + g)] * d

splitting the real interest rate contribution from the real growth contribution. This split is used in the analytical decomposition below.

Some alternative formulations omit the (1 + g) denominator, using a first-order approximation (r - g) * d. This framework uses the exact formulation with the (1 + g) scaling throughout.

## Analytical Decomposition

The total change in debt decomposes into three broad categories: automatic debt dynamics, the primary balance contribution, and stock-flow adjustments.

**Automatic debt dynamics** comprises four sub-components:

1. Real interest rate contribution: [r_t / (1 + g_t)] * d_{t-1}
2. Real growth contribution: [-g_t / (1 + g_t)] * d_{t-1}
3. Real exchange rate contribution: [z_t * d^f_{t-1}] / [(1 + g_t)(1 + pi^f_t)]
4. Relative inflation contribution: [(pi^d_t - pi^f_t) / ((1 + pi^f_t) * rho_t)] * d^f_{t-1}

**Primary balance contribution** equals -pb_t (negative of the primary balance, because surplus reduces debt).

**Stock-flow adjustment** equals sfa_t directly.

The sum of automatic debt dynamics, primary balance contribution, and stock-flow adjustment must equal the total change in debt.

## Gross Financing Needs

Gross financing needs (GFN) measure the total financing the sovereign must raise in a given period, combining new borrowing with rollover of maturing obligations:

    GFN_t = (-pb_t) + [i_t * d_{t-1} / rho_t] + amortization_t - interest_revenue_t

The first term is the primary deficit (negative of primary balance). The second term represents nominal interest expenditure expressed as a share of current GDP (scaled by the nominal GDP growth factor). Amortization represents the face value of maturing debt that must be refinanced. Interest revenue from government financial assets offsets total financing requirements.

## Debt-Stabilizing Primary Balance

The primary balance that would hold the debt ratio constant (delta_d = 0) assuming no exchange rate changes (z = 0) and no stock-flow adjustments (sfa = 0) is:

    pb* = [(r_t - g_t) / (1 + g_t)] * d_{t-1}
        + [(pi^d_t - pi^f_t) / ((1 + pi^f_t) * rho_t)] * d^f_{t-1}

Equivalently, this equals the sum of the real interest rate contribution, real growth contribution, and relative inflation contribution from the decomposition. When pb* > 0, a surplus is required to stabilize debt. When pb* < 0, debt stabilizes even with a deficit of that magnitude.

## Endogenous Risk Premium

For countries with market-determined interest rates, the effective nominal interest rate incorporates a risk premium that depends on the projected debt outlook. The risk premium is a function of the terminal (end-of-horizon) debt-to-GDP ratio:

    risk_premium = max(0, beta1 * (d_T - d_threshold))

where d_T is the debt-to-GDP ratio at the end of the projection horizon, d_threshold is the debt level above which markets begin pricing additional credit risk, and beta1 is the sensitivity coefficient. The configuration file specifies these parameters.

The effective interest rate for every projection year is the sum of the exogenous base rate and the uniform risk premium:

    i_t = i_base_t + risk_premium

Because the terminal debt d_T itself depends on the interest rates used throughout the trajectory, the system exhibits a circular dependency. The trajectory must be recomputed iteratively, updating the risk premium after each pass, until the terminal debt ratio stabilizes within the convergence tolerance.

Stress scenarios use the risk premium converged from the baseline trajectory. The stress path does not trigger a separate premium re-convergence.

## Contingent Liabilities

One-off fiscal shocks from contingent liability realizations (such as bank recapitalization costs or called guarantees) are recorded in the database. These shocks are additive to the stock-flow adjustment in the year they materialize.

## Consolidation Path

For countries assessed at "high" risk, the framework identifies the minimum constant primary balance adjustment - a uniform increment applied to the primary balance in every projection year - that would move the risk signal to at most "moderate". The search must find the adjustment to within the precision specified in the configuration.

When the country under consolidation also has an endogenous risk premium, the premium must be re-converged for each candidate adjustment level, since altering the fiscal path changes the terminal debt and therefore the market-implied interest rate.

## Notes

- Foreign-currency debt share alpha is treated as constant across the projection horizon: d^f_t = alpha * d_t at each point in time. In practice the FC share may evolve with new issuance and valuation effects, but this simplification is standard.
- The effective interest rate applies uniformly to the entire debt stock. In reality, the average rate reflects the weighted cost of instruments with varying maturities and coupon structures.
- All computations use end-of-period debt stocks. d_{t-1} is the stock at the end of the previous period.
