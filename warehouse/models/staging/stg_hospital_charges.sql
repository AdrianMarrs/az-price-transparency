-- One row per price, lightly standardized. The Python parser already cleaned text and
-- validated amounts, so this layer adds keys and flags rather than repairing data.

with source as (
    select * from {{ source('raw', 'hospital_charges') }}
)

select
    -- A row's identity is all of its values; md5 of the row text gives a stable key.
    md5(
        (ccn, description, code_type, code, setting, billing_class, modifiers,
         payer_name, plan_name, methodology, price_type, amount, algorithm)::text
    ) as price_id,
    state,
    ccn,
    source_file_id,
    code_type || ':' || upper(code) as service_key,
    upper(code) as code,
    code_type,
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
    -- TMC marks most inpatient line items as paid inside the stay's DRG case rate.
    coalesce(algorithm ilike '%bundled%', false) as is_bundled,
    loaded_at
from source
