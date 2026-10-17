-- One row per in-scope hospital: its DynamoDB PROFILE item (docs/03-cloud.md). Every
-- hospital gets one, including those with no usable prices, so the site can say why.
--
-- shoppable: for each of the CMS 70 shoppable services the hospital prices, the median
-- discounted cash price and median negotiated dollar price, and how many plans it lists.

with shoppable as (
    select
        f.ccn,
        json_agg(json_build_object(
            'service_key', f.service_key,
            'cms_shoppable_id', f.cms_shoppable_id,
            'description', s.cms_description,
            'cash', f.cash,
            'negotiated_median', f.negotiated_median,
            'plans', f.plans
        ) order by f.cms_shoppable_id, f.service_key) as shoppable,
        count(*) as shoppable_services
    from (
        select
            ccn,
            service_key,
            cms_shoppable_id,
            round((percentile_cont(0.5) within group (order by amount)
                filter (where price_type = 'discounted_cash'))::numeric, 2) as cash,
            round((percentile_cont(0.5) within group (order by amount)
                filter (where price_type = 'negotiated_dollar'))::numeric, 2) as negotiated_median,
            count(distinct (payer_name, plan_name)) filter (where payer_name is not null) as plans
        from {{ ref('fct_prices') }}
        where cms_shoppable_id is not null and source = 'hospital'
        group by ccn, service_key, cms_shoppable_id
    ) as f
    left join {{ ref('dim_services') }} as s using (service_key)
    group by f.ccn
),

services as (
    select ccn, count(distinct service_key) as services
    from {{ ref('fct_prices') }}
    where source = 'hospital'
    group by ccn
),

final as (
    select
        'HOSPITAL#' || h.ccn as pk,
        'PROFILE' as sk,
        h.ccn,
        json_build_object(
            'ccn', h.ccn,
            'name', h.name,
            'address', h.address,
            'city', h.city,
            'zip', h.zip,
            'county', h.county,
            'hospital_type', h.hospital_type,
            'ownership', h.ownership,
            'price_file_status', h.price_file_status,
            'mrf_url', h.mrf_url,
            'score_pct', c.score_pct,
            'rules_checked', c.rules_checked,
            'rules_passed', c.rules_passed,
            'failed_rules', c.failed_rules,
            'services', coalesce(v.services, 0),
            'shoppable_services', coalesce(sh.shoppable_services, 0),
            'shoppable', coalesce(sh.shoppable, '[]')
        ) as item
    from {{ ref('dim_hospitals') }} as h
    inner join {{ ref('hospital_compliance_scores') }} as c using (ccn)
    left join services as v using (ccn)
    left join shoppable as sh using (ccn)
    where not h.federally_run
)

select
    pk || '|' || sk as item_key,
    pk,
    sk,
    ccn,
    item::text as item,
    md5(item::text) as content_hash,
    octet_length(item::text) as item_bytes
from final
