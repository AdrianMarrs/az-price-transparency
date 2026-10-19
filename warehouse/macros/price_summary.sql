-- The query behind marts.price_summary, for one bucket of services (macros/bucket_hooks.sql).

{% macro price_summary_bucket(bucket, buckets) %}
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
        -- market comes from payer + plan (a "Work Comp" plan under a commercial payer)
        left join {{ ref('dim_payer_plans') }} as p
            on p.payer_name = f.payer_name and p.plan_name is not distinct from f.plan_name
        where f.source = 'hospital'
          and f.price_type in ('negotiated_dollar', 'discounted_cash', 'gross')
          and coalesce(p.market, '') not in ('self_pay')
          -- $1-or-less insurer prices are case-rate placeholders, not prices
          and not (f.price_type = 'negotiated_dollar' and coalesce(f.amount <= 1, false))
          and hash(f.service_key) % {{ buckets }} = {{ bucket }}
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
            -- one sorted copy of the prices for all three quartiles, not one each
            quantile_cont(amount, [0.25, 0.50, 0.75]) as quartiles,
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
        geography, service_key, setting, billing_class, price_type, market,
        prices, total_amount, mean_amount, min_amount,
        quartiles[1] as p25_amount,
        quartiles[2] as median_amount,
        quartiles[3] as p75_amount,
        max_amount
    from summarized
{% endmacro %}
