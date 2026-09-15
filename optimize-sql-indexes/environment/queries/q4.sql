-- Employee sales lookup: sales by specific employee with join
SELECT e.first_name, e.last_name, s.sale_date, s.eur_value
FROM employees e
JOIN sales s ON e.employee_id = s.employee_id
            AND e.subsidiary_id = s.subsidiary_id
WHERE e.subsidiary_id = 10
  AND e.last_name = 'Smith'
ORDER BY s.sale_date DESC
LIMIT 50;
