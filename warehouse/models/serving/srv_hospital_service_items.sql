-- One row per hospital x service: its DynamoDB item (key design in docs/03-cloud.md).
--
-- prices: one entry per payer x plan x setting x price type, with the payer's parent
-- company and market, the most common methodology, the median amount and how many rows
-- it summarizes (a file can list the same plan several times, e.g. per modifier).
-- standard: the prices that aren't insurer-specific (gross, discounted cash, min, max).
--
-- The JSON is built in a fixed order, so the same input always gives the same text and
-- the same content_hash: the export writes only items whose hash changed.

with grouped as (
    select
        f.ccn,
        f.service_key,
        f.payer_name,
        f.plan_name,
        p.payer_group,
        p.market,
        f.setting,
        f.price_type,
        mode() within group (order by f.methodology) as methodology,
        round((percentile_cont(0.5) within group (order by f.amount))::numeric, 2) as amount,
        min(f.algorithm) as algorithm,
        bool_or(f.is_bundled) as bundled,
        count(*) as n
    from {{ ref('fct_prices') }} as f
    left join {{ ref('dim_payer_plans') }} as p
        on p.payer_plan_key = md5((f.payer_name, f.plan_name)::text)
    where f.source = 'hospital'
    group by 1, 2, 3, 4, 5, 6, 7, 8
),

items as (
    select
        ccn,
        service_key,
        coalesce(json_agg(json_build_object(
            'payer', payer_name,
            'plan', plan_name,
            'group', payer_group,
            'market', market,
            'setting', setting,
            'type', price_type,
            'method', methodology,
            'amount', amount,
            'algorithm', left(algorithm, 200),
            'bundled', bundled,
            'n', n
        ) order by payer_name, plan_name, setting, price_type)
            filter (where payer_name is not null), '[]') as prices,
        coalesce(json_agg(json_build_object(
            'setting', setting,
            'type', price_type,
            'amount', amount,
            'n', n
        ) order by setting, price_type)
            filter (where payer_name is null), '[]') as standard,
        count(distinct (payer_name, plan_name)) filter (where payer_name is not null) as plans
    from grouped
    group by ccn, service_key
),

final as (
    select
        'HOSPITAL#' || i.ccn as pk,
        'SERVICE#' || i.service_key as sk,
        'SERVICE#' || i.service_key as gsi1pk,
        'HOSPITAL#' || i.ccn as gsi1sk,
        i.ccn,
        i.service_key,
        json_build_object(
            'ccn', i.ccn,
            'service_key', i.service_key,
            'code', s.code,
            'code_type', s.code_type,
            'description', s.common_description,
            'cms_shoppable_id', s.cms_shoppable_id,
            'plans', i.plans,
            'standard', i.standard,
            'prices', i.prices
        ) as item
    from items as i
    left join {{ ref('dim_services') }} as s using (service_key)
)

select
    pk || '|' || sk as item_key,
    pk,
    sk,
    gsi1pk,
    gsi1sk,
    ccn,
    service_key,
    item::text as item,
    md5(item::text) as content_hash,
    octet_length(item::text) as item_bytes
from final
