-- One row per hospital x service x payer x plan x setting x price type: the rows a service's
-- data file is made of. serving/export_static.py streams them in service order and builds
-- each data/<state>/services/<slug>.json, so no JSON is assembled here (building every
-- list in SQL needed more memory than DuckDB could spill; at every state it would be ~60x).
--
-- payer_name is null for the prices that aren't insurer-specific (gross, discounted cash,
-- min, max): a file's "standard" list. methodology is the most common one in the group
-- (ties: the first alphabetically), amount the median, n how many rows it summarizes
-- (a file can list the same plan several times, e.g. per modifier).

with prices as (
    select
        h.state,
        f.ccn,
        f.service_key,
        f.payer_name,
        f.plan_name,
        p.payer_group,
        p.market,
        f.setting,
        f.price_type,
        f.methodology,
        f.amount,
        f.algorithm,
        f.is_bundled
    from {{ ref('fct_prices') }} as f
    join {{ ref('dim_hospitals') }} as h using (ccn)
    left join {{ ref('dim_payer_plans') }} as p
        on p.payer_name = f.payer_name and p.plan_name is not distinct from f.plan_name
    where f.source = 'hospital'
),

methodology_counts as (
    select ccn, service_key, payer_name, plan_name, setting, price_type, methodology, count(*) as n
    from prices
    group by ccn, service_key, payer_name, plan_name, setting, price_type, methodology
),

methodologies as (
    select ccn, service_key, payer_name, plan_name, setting, price_type,
           min(methodology) as methodology
    from (
        select *, max(n) over (
            partition by ccn, service_key, payer_name, plan_name, setting, price_type) as top
        from methodology_counts
    ) as c
    where n = top
    group by ccn, service_key, payer_name, plan_name, setting, price_type
)

select
    g.state,
    g.service_key,
    g.ccn,
    g.payer_name,
    g.plan_name,
    any_value(g.payer_group) as payer_group,
    any_value(g.market) as market,
    g.setting,
    g.price_type,
    any_value(m.methodology) as methodology,
    -- rounded as a decimal, then cast: a double's .975 is .97499..., which Postgres didn't do
    round(percentile_cont(0.5) within group (order by g.amount), 2)::double as amount,
    left(min(g.algorithm), 200) as algorithm,
    bool_or(g.is_bundled) as bundled,
    count(*) as n
from prices as g
left join methodologies as m
    on m.ccn = g.ccn and m.service_key = g.service_key
    and m.payer_name is not distinct from g.payer_name
    and m.plan_name is not distinct from g.plan_name
    and m.setting = g.setting and m.price_type = g.price_type
group by g.state, g.service_key, g.ccn, g.payer_name, g.plan_name, g.setting, g.price_type
