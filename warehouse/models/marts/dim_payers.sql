-- One row per payer name as hospitals write it, mapped to a parent company (payer_group)
-- and a market by the payer_aliases seed. Names the seed doesn't cover show up as
-- market = 'unmapped' (a warning-level test lists them).

with payers as (
    select distinct payer_name
    from {{ ref('stg_hospital_charges') }}
    where payer_name is not null
)

select
    p.payer_name,
    coalesce(a.payer_group, p.payer_name) as payer_group,
    coalesce(a.market, 'unmapped') as market,
    a.payer_name is not null as is_mapped,
    a.notes
from payers as p
left join {{ ref('payer_aliases') }} as a using (payer_name)
