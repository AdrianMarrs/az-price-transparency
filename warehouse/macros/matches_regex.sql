{#
  Case-insensitive regular-expression match: Postgres's ~*, DuckDB's regexp_matches(.., 'i').
  The seed patterns use Postgres's word boundaries \m and \M; DuckDB's engine (RE2) writes
  both as \b.
#}
{% macro matches_regex(text, pattern) -%}
  {%- if target.type == 'duckdb' -%}
    regexp_matches({{ text }}, replace(replace({{ pattern }}, '\m', '\b'), '\M', '\b'), 'i')
  {%- else -%}
    {{ text }} ~* {{ pattern }}
  {%- endif -%}
{%- endmacro %}
