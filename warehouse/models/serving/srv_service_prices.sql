{%- set buckets = 16 -%}
{{ config(post_hook=bucket_hooks('srv_service_prices_bucket', buckets)) }}

-- One row per hospital x service x payer x plan x setting x price type: the rows a service's
-- data file is made of. serving/export_static.py streams them in service order and builds
-- each data/<state>/services/<slug>.json, so no JSON is assembled here (building every
-- list in SQL needed more memory than DuckDB could spill; at every state it would be ~60x).
--
-- payer_name is null for the prices that aren't insurer-specific (gross, discounted cash,
-- min, max): a file's "standard" list. methodology is the most common one in the group
-- (ties: the first alphabetically), amount the median, n how many rows it summarizes
-- (a file can list the same plan several times, e.g. per modifier).
--
-- Built in 16 buckets of services, one statement each (macros/bucket_hooks.sql); the query
-- is in macros/srv_service_prices.sql.

{{ srv_service_prices_bucket(0, buckets) }}
