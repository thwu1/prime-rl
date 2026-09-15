# Business Analytics Reports — Requirements

The analytics team built a star schema data warehouse from TPC-H operational
data. Five reports have been developed against this model to support business
decision-making. Each report must produce numbers that exactly match the
operational source of truth.

## Report 1: Pricing Summary
Summarize all shipped line items by return flag and line status. Include total
and average quantities, prices, discounts, tax-inclusive charges, and line
counts. Only include items shipped on or before September 2, 1998.

## Report 2: Order Revenue by Customer Region
Show total order value and number of orders by customer geographic region for
orders placed in calendar year 1995.

## Report 3: Local Supplier Revenue in ASIA
Calculate revenue from transactions where the customer and supplier are in the
same nation within the ASIA region. Consider orders placed in calendar year 1994.

## Report 4: Profit by Supplier Nation
Calculate net profit (revenue minus actual cost of goods) by supplier nation and
order year for all parts containing "green" in the part name. The cost must
reflect the actual supply cost for each specific part-supplier combination, not
the part's catalog retail price.

## Report 5: Annual Revenue Trend
Show quarterly revenue and distinct order counts across all available years in
the dataset. This report is critical for multi-year trend analysis and must
include data from the full operational timeline.
