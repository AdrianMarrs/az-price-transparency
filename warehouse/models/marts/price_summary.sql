{%- set buckets = 16 -%}
{%- set hooks = [] -%}
{%- for b in range(1, buckets) -%}
    {%- do hooks.append('insert into {{ this }} {{ price_summary_bucket(' ~ b ~ ', ' ~ buckets ~ ') }}') -%}
{%- endfor -%}
{{ config(indexes=[{'columns': ['service_key', 'geography']}], post_hook=hooks) }}

-- Price statistics per service, for first-pass comparisons before drilling into fct_prices.
--
-- Grain: geography (a state, or US) x service x setting x billing class x price type x
-- market ('all' = every market together). National rows are computed from the individual
-- prices, never from the state rows: medians can't be combined, and averaging state
-- averages would weight a state with 12 prices like one with 10,000. sum and count are
-- kept so averages can be recombined correctly anywhere.

-- Built in 16 buckets of services, one statement each so each holds 1/16 of the prices in
-- memory (macros/price_summary.sql): the first bucket creates the table, the rest are
-- inserted after it.

{{ price_summary_bucket(0, buckets) }}
