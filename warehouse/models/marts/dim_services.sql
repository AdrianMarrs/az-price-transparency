-- One row per service code. Hospitals describe the same code differently, so the most
-- common description is kept (ties: the first alphabetically), plus CMS's plain-language
-- name for the 70 shoppable ones. Counted out explicitly rather than with mode(), which
-- DuckDB computes slowly and breaks ties in no fixed order.

with codes as (
    select
        service_key,
        code,
        code_type,
        max(cms_shoppable_id) as cms_shoppable_id,
        count(distinct ccn) as hospitals
    from {{ ref('stg_hospital_charges') }}
    group by service_key, code, code_type
),

description_counts as (
    select service_key, description, count(*) as n
    from {{ ref('stg_hospital_charges') }}
    group by service_key, description
),

common as (
    select service_key, description
    from (
        select
            service_key,
            description,
            row_number() over (partition by service_key order by n desc, description) as rank
        from description_counts
    ) as ranked
    where rank = 1
),

cms as (
    select distinct on (service_id) service_id, description, category
    from {{ ref('shoppable_services') }}
    order by service_id
)

select
    codes.service_key,
    codes.code,
    codes.code_type,
    common.description as common_description,
    codes.cms_shoppable_id,
    codes.hospitals,
    cms.description as cms_description,
    cms.category as cms_category
from codes
join common on common.service_key = codes.service_key
left join cms on cms.service_id = codes.cms_shoppable_id
