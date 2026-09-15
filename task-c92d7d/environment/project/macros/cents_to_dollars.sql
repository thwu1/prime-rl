{% macro cents_to_dollars(column_name) %}
    ({{ col }} / 100.0)
{% endmacro %}
