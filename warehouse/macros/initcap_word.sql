{# First letter upper, the rest lower ("cigna" -> "Cigna"): Postgres's initcap for a single
   word, which DuckDB lacks. #}
{% macro initcap_word(text) -%}
  upper(left({{ text }}, 1)) || lower(substr({{ text }}, 2))
{%- endmacro %}
