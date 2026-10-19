{%- set buckets = 16 -%}
{{ config(indexes=[{'columns': ['service_key', 'geography']}], post_hook=bucket_hooks('price_summary_bucket', buckets)) }}

-- Price statistics per service, for first-pass comparisons before drilling into fct_prices.
--
-- Grain: geography (a state, or US) x service x setting x billing class x price type x
-- market ('all' = every market together). National rows are computed from the individual
-- prices, never from the state rows: medians can't be combined, and averaging state
-- averages would weight a state with 12 prices like one with 10,000. sum and count are
-- kept so averages can be recombined correctly anywhere.

-- Built in 16 buckets of services, one statement each (macros/bucket_hooks.sql); the query
-- is in macros/price_summary.sql.

{{ price_summary_bucket(0, buckets) }}
