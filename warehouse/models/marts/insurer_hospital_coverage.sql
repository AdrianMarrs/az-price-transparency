-- One row per in-scope Arizona hospital x insurer: does the insurer's own data include it,
-- and does the hospital's price file list that insurer?
--
-- coverage:
--   both                 the insurer publishes rates for it, and its file lists the insurer
--   insurer_only         rates from the insurer; the hospital's file doesn't name it
--   hospital_file_only   the hospital's file names the insurer; the insurer's files don't
--                        include the hospital's own NPIs
--   neither
-- comparable_rates counts the rates that reached fct_prices (a code some hospital prices);
-- a hospital paid per day or by percentage of charges has rates but none comparable.

with hospitals as (
    select ccn, name, hospital_type
    from {{ ref('dim_hospitals') }}
    where not federally_run
),

insurers as (
    select distinct insurer, {{ initcap_word('insurer') }} as payer_group from {{ ref('stg_insurer_rates') }}
),

npis as (
    select ccn, count(*) as hospital_npis
    from {{ ref('hospital_npis') }}
    where role = 'hospital'
    group by ccn
),

insurer_rates as (
    select
        insurer, ccn,
        count(distinct network) as networks,
        count(*) as rates,
        count(*) filter (where code_type in ('CPT/HCPCS', 'MS-DRG')) as coded_rates
    from {{ ref('stg_insurer_rates') }}
    group by 1, 2
),

comparable as (
    select lower(payer_name) as insurer, ccn, count(*) as comparable_rates
    from {{ ref('fct_prices') }}
    where source = 'insurer'
    group by 1, 2
),

-- every hospital file's payer names, including hospitals whose prices aren't loaded
listed as (
    select distinct pp.ccn, d.payer_group
    from {{ source('raw', 'payer_plans') }} as pp
    join {{ ref('dim_payer_plans') }} as d
        on d.payer_name = pp.payer_name and d.plan_name is not distinct from pp.plan_name
)

select
    h.ccn || '|' || i.insurer as coverage_key,
    h.ccn,
    h.name,
    h.hospital_type,
    i.insurer,
    coalesce(n.hospital_npis, 0) as hospital_npis,
    coalesce(r.networks, 0) as networks,
    coalesce(r.rates, 0) as rates,
    coalesce(r.coded_rates, 0) as coded_rates,
    coalesce(c.comparable_rates, 0) as comparable_rates,
    l.ccn is not null as listed_in_hospital_file,
    case
        when r.ccn is not null and l.ccn is not null then 'both'
        when r.ccn is not null then 'insurer_only'
        when l.ccn is not null then 'hospital_file_only'
        else 'neither'
    end as coverage
from hospitals as h
cross join insurers as i
left join npis as n on n.ccn = h.ccn
left join insurer_rates as r on r.ccn = h.ccn and r.insurer = i.insurer
left join comparable as c on c.ccn = h.ccn and c.insurer = i.insurer
left join listed as l on l.ccn = h.ccn and l.payer_group = i.payer_group
