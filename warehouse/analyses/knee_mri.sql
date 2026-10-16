-- What does a knee MRI without contrast (CPT 73721) cost at each Pima County hospital,
-- by insurer?
--
-- Compile, then run the SQL dbt writes (refs become real table names):
--   uv run dbt compile --project-dir warehouse --profiles-dir warehouse --select knee_mri
--   -> warehouse/target/compiled/az_prices/analyses/knee_mri.sql
--
-- Scope: the hospital (facility) charge for an outpatient scan, which is how a scheduled
-- MRI is billed; the radiologist's reading is billed separately. Only insurer markets a
-- patient can compare (not travel, workers' comp, correctional, network rental, ...).

with mri as (
    select
        h.name as hospital,
        f.description,
        f.price_type,
        f.payer_name,
        f.plan_name,
        p.payer_group,
        p.market,
        f.amount
    from {{ ref('fct_prices') }} as f
    join {{ ref('dim_hospitals') }} as h using (ccn)
    left join {{ ref('dim_payer_plans') }} as p
        on p.payer_name = f.payer_name and p.plan_name is not distinct from f.plan_name
    where f.service_key = 'CPT/HCPCS:73721'
      and f.setting in ('outpatient', 'both')
      and f.billing_class = 'facility'
),

cash as (
    select hospital, min(amount) as cash_price
    from mri
    where price_type = 'discounted_cash'
    group by hospital
),

negotiated as (
    -- Some hospitals list the scan on more than one chargemaster line (e.g. one side vs.
    -- both knees), so keep the range across lines rather than picking one silently.
    select
        payer_group,
        market,
        hospital,
        plan_name,
        min(amount) as low,
        max(amount) as high,
        count(*) as lines
    from mri
    where price_type = 'negotiated_dollar'
      and market in ('commercial', 'medicare_advantage', 'medicaid', 'exchange', 'mixed')
    group by payer_group, market, hospital, plan_name
)

select
    n.payer_group,
    n.market,
    n.hospital,
    n.plan_name,
    n.low,
    nullif(n.high, n.low) as high_if_different,
    c.cash_price
from negotiated as n
left join cash as c using (hospital)
order by n.payer_group, n.market, n.low
