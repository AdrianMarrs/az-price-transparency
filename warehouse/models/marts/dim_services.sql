-- One row per service code. Hospitals describe the same code differently, so the most
-- common description is kept, plus CMS's plain-language name for the 70 shoppable ones.

with codes as (
    select
        service_key,
        code,
        code_type,
        mode() within group (order by description) as common_description,
        max(cms_shoppable_id) as cms_shoppable_id,
        count(distinct ccn) as hospitals
    from {{ ref('stg_hospital_charges') }}
    group by service_key, code, code_type
),

cms as (
    select distinct on (service_id) service_id, description, category
    from {{ ref('shoppable_services') }}
    order by service_id
)

select
    codes.*,
    cms.description as cms_description,
    cms.category as cms_category
from codes
left join cms on cms.service_id = codes.cms_shoppable_id
