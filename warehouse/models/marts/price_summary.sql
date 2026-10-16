{{ config(indexes=[{'columns': ['service_key', 'geography']}]) }}

-- Price statistics per service, for first-pass comparisons before drilling into fct_prices.
--
-- Grain: geography (a state, or US) x service x setting x billing class x price type x
-- market ('all' = every market together). National rows are computed from the individual
-- prices, never from the state rows: medians can't be combined, and averaging state
-- averages would weight a state with 12 prices like one with 10,000. sum and count are
-- kept so averages can be recombined correctly anywhere.

with prices as (
    select
        f.state,
        f.service_key,
        f.setting,
        f.billing_class,
        f.price_type,
        p.market,
        f.amount
    from {{ ref('fct_prices') }} as f
    left join {{ ref('dim_payers') }} as p using (payer_name)
    where f.price_type in ('negotiated_dollar', 'discounted_cash', 'gross')
      and coalesce(p.market, '') not in ('self_pay')
),

summarized as (
    select
        case when grouping(state) = 1 then 'US' else state end as geography,
        service_key,
        setting,
        billing_class,
        price_type,
        case when grouping(market) = 1 then 'all' else coalesce(market, 'none') end as market,
        count(*) as prices,
        sum(amount) as total_amount,
        round(sum(amount) / count(*), 2) as mean_amount,
        min(amount) as min_amount,
        percentile_cont(0.25) within group (order by amount) as p25_amount,
        percentile_cont(0.50) within group (order by amount) as median_amount,
        percentile_cont(0.75) within group (order by amount) as p75_amount,
        max(amount) as max_amount
    from prices
    group by grouping sets (
        (state, service_key, setting, billing_class, price_type, market),
        (state, service_key, setting, billing_class, price_type),
        (service_key, setting, billing_class, price_type, market),
        (service_key, setting, billing_class, price_type)
    )
)

select
    md5((geography, service_key, setting, billing_class, price_type, market)::text)
        as summary_key,
    *
from summarized
