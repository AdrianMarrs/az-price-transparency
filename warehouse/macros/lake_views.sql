{#
  DuckDB target: the raw tables are views over the Parquet lake (ingest/lake.py), created at
  the start of every run, so sources resolve to raw.<table> on either database and unit
  tests can read their columns. Folder names (ccn=030006) stay text, not numbers. LAKE is a folder (data/lake) or an S3 prefix.
#}
{% macro create_lake_views() %}
  {% if target.type == 'duckdb' and execute %}
    {% set lake = env_var('LAKE', 'data/lake') %}
    {% set tables = {
      'hospital_charges': 'raw/hospital_charges/*/*/*.parquet',
      'insurer_rates': 'raw/insurer_rates/*/*/*/*.parquet',
      'source_files': 'raw/source_files/*.parquet',
      'compliance_checks': 'raw/compliance_checks/*.parquet',
      'payer_plans': 'raw/payer_plans/*.parquet',
    } %}
    {% if lake.startswith('s3://') %}
      {# The cloud run's credentials (the task role), for read_parquet on S3. #}
      {% do run_query("create or replace secret lake (type s3, provider credential_chain)") %}
    {% endif %}
    {% do run_query('create schema if not exists raw') %}
    {% for name, glob in tables.items() %}
      {# A table with no files yet (no downloads in CI) gets no view; read_parquet would fail. #}
      {% set found = run_query("select count(*) from glob('" ~ lake ~ "/" ~ glob ~ "')").columns[0].values()[0] %}
      {% if found == 0 %}
        {% do log("lake: no files for raw." ~ name ~ ", so no view", info=true) %}
      {% else %}
        {% do run_query(
          "create or replace view raw." ~ name ~ " as select * from read_parquet('" ~ lake ~ "/" ~ glob
          ~ "', hive_partitioning = true, hive_types_autocast = false, union_by_name = true)"
        ) %}
      {% endif %}
    {% endfor %}
  {% endif %}
{% endmacro %}
