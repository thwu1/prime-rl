-- Employee directory: find employees at subsidiary 5 born more than 30 years ago
SELECT employee_id, subsidiary_id, first_name, last_name, date_of_birth
FROM employees
WHERE subsidiary_id = 5
  AND date_of_birth + INTERVAL '30 years' < CURRENT_DATE
ORDER BY last_name, first_name;
