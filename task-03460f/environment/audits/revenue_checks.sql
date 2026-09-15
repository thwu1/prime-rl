/* Audit: asserts that revenue values are non-negative.
   Returns rows that violate the data quality rule (should return 0 rows on success). */
AUDIT (
  name assert_positive_revenue
);

SELECT *
FROM @this_model
WHERE total_revenue >= 0
