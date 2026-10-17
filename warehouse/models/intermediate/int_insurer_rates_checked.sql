{{ config(materialized='table') }}

-- Insurer rates with a rate_flag, so odd values are labelled rather than loaded silently.
--
-- Impossible (dropped from fct_prices):
--   not_positive         a dollar or percentage rate of zero or less
--   percentage_over_100  a percentage of billed charges above 100
-- Outliers (kept in fct_prices, flagged; some are real, e.g. a children's hospital's drug
-- pricing):
--   over_10x_peers       more than 10x the median for the same code, setting, billing class,
--   under_tenth_of_peers   price type and modifiers across Arizona hospitals; or under a tenth
--
-- Peers are distinct prices, so a contract repeated across a dozen networks counts once,
-- and a median needs at least 5 hospitals to be a fair comparison. Absolute limits would be
-- wrong: $0.02 is a real rate for "prednisone, 1 mg" and $700,000 for a severe-burns DRG.

with rates as (
    select * from {{ ref('stg_insurer_rates') }}
),

distinct_prices as (
    select distinct
        insurer, ccn, service_key, setting, billing_class, price_type,
        coalesce(modifiers, '') as modifiers, amount
    from rates
    where amount > 0
),

peers as (
    select
        insurer, service_key, setting, billing_class, price_type, modifiers,
        percentile_cont(0.5) within group (order by amount) as peer_median,
        count(distinct ccn) as peer_hospitals
    from distinct_prices
    group by 1, 2, 3, 4, 5, 6
)

select
    r.*,
    p.peer_median,
    p.peer_hospitals,
    case
        when r.amount <= 0 then 'not_positive'
        when r.price_type = 'negotiated_percentage' and r.amount > 100 then 'percentage_over_100'
        when p.peer_hospitals >= 5 and r.amount > 10 * p.peer_median then 'over_10x_peers'
        when p.peer_hospitals >= 5 and r.amount < p.peer_median / 10 then 'under_tenth_of_peers'
    end as rate_flag
from rates as r
left join peers as p
    on p.insurer = r.insurer
    and p.service_key = r.service_key
    and p.setting = r.setting
    and p.billing_class is not distinct from r.billing_class
    and p.price_type = r.price_type
    and p.modifiers = coalesce(r.modifiers, '')
