{{ config(indexes=[
    {'columns': ['service_key']},
    {'columns': ['ccn']},
]) }}

-- One row per hospital price. Join to dim_hospitals (ccn), dim_services (service_key) and
-- dim_payers (payer_name; null for list, cash, min and max prices).

select
    price_id,
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
