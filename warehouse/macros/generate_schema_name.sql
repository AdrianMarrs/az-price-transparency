{#
  Use the folder's schema name as-is ("staging", "marts", "reference") instead of dbt's
  default of prefixing it with the target schema ("analytics_staging").
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ custom_schema_name if custom_schema_name else target.schema }}
{%- endmacro %}
