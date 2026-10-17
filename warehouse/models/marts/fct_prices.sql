{{ config(indexes=[
    {'columns': ['service_key']},
    {'columns': ['ccn']},
]) }}

-- One row per price. Join to dim_hospitals (ccn), dim_services (service_key) and
-- dim_payers (payer_name; null for list, cash, min and max prices).
--
-- source says who published it: 'hospital' (the hospital's own price file) or 'insurer'
-- (an insurer's Transparency in Coverage file; payer_name is the insurer, plan_name its
-- network). Insurer rates are kept only for codes some hospital prices, so every row has
-- a dim_services entry. The serving models read hospital rows only.

with hospital as (
    select
        price_id,
        'hospital' as source,
        state,
        ccn,
        service_key,
        cms_shoppable_id,
        description,
        setting,
        billing_class,
        modifiers,
        payer_name,
        plan_name,
        methodology,
        price_type,
        amount,
        algorithm,
        is_bundled,
        source_file_id
    from {{ ref('stg_hospital_charges') }}
),

insurer as (
    select
        r.price_id,
        'insurer' as source,
        r.state,
        r.ccn,
        r.service_key,
        s.cms_shoppable_id,
        r.description,
        r.setting,
        r.billing_class,
        r.modifiers,
        initcap(r.insurer) as payer_name,
        r.network as plan_name,
        r.methodology,
        r.price_type,
        r.amount,
        null::text as algorithm,
        false as is_bundled,
        null::bigint as source_file_id
    from {{ ref('stg_insurer_rates') }} as r
    join {{ ref('dim_services') }} as s using (service_key)
)

select * from hospital
union all
select * from insurer
