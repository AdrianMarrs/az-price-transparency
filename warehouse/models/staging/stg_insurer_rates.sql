-- One row per insurer-published rate for an Arizona hospital, in fct_prices' vocabulary.
--
-- Transparency in Coverage names things differently from hospital files: CPT and HCPCS are
-- separate code types (hospitals combine them), "institutional" is the facility charge, and
-- negotiated_type says how the rate is expressed. Codes other than CPT, HCPCS and MS-DRG
-- (revenue codes, APCs, ICD, custom) are kept here but don't reach fct_prices.

with source as (
    select * from {{ source('raw', 'insurer_rates') }}
),

mapped as (
    select
        *,
        case
            when billing_code_type in ('CPT', 'HCPCS') then 'CPT/HCPCS'
            else billing_code_type
        end as code_type
    from source
)

select
    md5(
        (insurer, network, month, ccn, billing_code_type, billing_code, negotiation_arrangement,
         negotiated_type, negotiated_rate, billing_class, setting, service_codes, modifiers,
         expiration_date)::text
    ) as price_id,
    'AZ' as state,
    ccn,
    insurer,
    network,
    month,
    code_type || ':' || upper(billing_code) as service_key,
    upper(billing_code) as code,
    code_type,
    billing_code_type,
    description,
    setting,
    case billing_class when 'institutional' then 'facility' else billing_class end as billing_class,
    modifiers,
    service_codes,
    negotiation_arrangement,
    case negotiated_type
        when 'fee schedule' then 'fee schedule'
        when 'per diem' then 'per diem'
        when 'percentage' then 'percent of total billed charges'
        else 'other'  -- negotiated, derived
    end as methodology,
    case
        when negotiated_type = 'percentage' then 'negotiated_percentage'
        else 'negotiated_dollar'
    end as price_type,
    negotiated_type,
    negotiated_rate::numeric(18, 4) as amount,
    expiration_date,
    loaded_at
from mapped
