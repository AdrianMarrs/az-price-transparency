-- One row per payer name x plan name, mapped to a parent company and a market.
--
-- Payer group: an exact row in payer_aliases wins; otherwise the first matching pattern in
-- payer_group_patterns (by priority); otherwise the payer name itself.
-- Market, from the payer and plan names together (plans often say "Medicaid" or "Work
-- Comp" when the payer name doesn't): a strong pattern wins; then the alias's market unless
-- it's mixed or unknown; then a weak pattern; then the alias's market; else 'unknown'.

with names as (
    select payer_name, plan_name, ccn, rows from {{ source('raw', 'payer_plans') }}
    union all
    select payer_name, plan_name, ccn, count(*) as rows
    from {{ ref('stg_hospital_charges') }}
    where payer_name is not null
    group by payer_name, plan_name, ccn
),

payer_plans as (
    select
        payer_name,
        plan_name,
        payer_name || ' | ' || coalesce(plan_name, '') as search_text,
        max(rows) as rows,  -- a hospital can be in both inputs; don't double count
        count(distinct ccn) as hospitals
    from names
    group by payer_name, plan_name
),

group_match as (
    select distinct on (p.payer_name) p.payer_name, g.payer_group
    from (select distinct payer_name from payer_plans) as p
    join {{ ref('payer_group_patterns') }} as g on p.payer_name ~* g.pattern
    order by p.payer_name, g.priority
),

market_match as (
    select distinct on (p.payer_name, p.plan_name, m.strength)
        p.payer_name, p.plan_name, m.strength, m.market
    from payer_plans as p
    join {{ ref('market_patterns') }} as m on p.search_text ~* m.pattern
    order by p.payer_name, p.plan_name, m.strength, m.priority
)

select
    md5((p.payer_name, p.plan_name)::text) as payer_plan_key,
    p.payer_name,
    p.plan_name,
    coalesce(a.payer_group, g.payer_group, p.payer_name) as payer_group,
    case
        when a.payer_name is not null then 'alias'
        when g.payer_group is not null then 'pattern'
        else 'none'
    end as group_source,
    coalesce(
        strong.market,
        case when a.market not in ('mixed', 'unknown') then a.market end,
        weak.market,
        a.market,
        'unknown'
    ) as market,
    case
        when strong.market is not null then 'strong_pattern'
        when a.market not in ('mixed', 'unknown') then 'alias'
        when weak.market is not null then 'weak_pattern'
        else 'none'
    end as market_source,
    p.rows,
    p.hospitals
from payer_plans as p
left join {{ ref('payer_aliases') }} as a using (payer_name)
left join group_match as g using (payer_name)
left join market_match as strong
    on strong.payer_name = p.payer_name
    and strong.plan_name is not distinct from p.plan_name
    and strong.strength = 'strong'
left join market_match as weak
    on weak.payer_name = p.payer_name
    and weak.plan_name is not distinct from p.plan_name
    and weak.strength = 'weak'
