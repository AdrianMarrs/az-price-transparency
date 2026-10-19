-- For a model built in buckets of services, one statement each: the model's own query is
-- bucket 0, and these post-hooks insert buckets 1 to buckets - 1 after it. `name` is a
-- macro taking (bucket, buckets) that returns the query for one bucket, keeping the rows
-- whose hash(service_key) % buckets is that bucket. Only for a model whose every group
-- includes the service, so no group is split across buckets.
--
-- Why: DuckDB keeps an exact median's prices in memory (outside its memory limit), and a
-- big grouping spills to disk; across the country price_summary ran out of memory on a
-- 120 GB task and srv_service_prices filled a 100 GB disk (October 2026). Each statement
-- holds only its bucket's share.

{% macro bucket_hooks(name, buckets) %}
    {%- set hooks = [] -%}
    {%- for b in range(1, buckets) -%}
        {%- do hooks.append('insert into {{ this }} {{ ' ~ name ~ '(' ~ b ~ ', ' ~ buckets ~ ') }}') -%}
    {%- endfor -%}
    {{ return(hooks) }}
{% endmacro %}
