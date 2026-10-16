-- One row per in-scope hospital: how many of the price transparency rules it passes.
-- score_pct counts only rules that could be checked; rules_checked says how many that was,
-- so a hospital whose file couldn't be obtained shows a low count, not a flattering score.

with checks as (
    select * from {{ source('raw', 'compliance_checks') }}
)

select
    h.ccn,
    h.name,
    h.city,
    h.hospital_type,
    h.ownership,
    h.price_file_status,
    count(*) filter (where c.passed is not null) as rules_checked,
    count(*) filter (where c.passed) as rules_passed,
    round(
        100.0 * count(*) filter (where c.passed)
        / nullif(count(*) filter (where c.passed is not null), 0)
    ) as score_pct,
    string_agg(c.rule, ', ' order by c.rule) filter (where not c.passed) as failed_rules
from {{ ref('dim_hospitals') }} as h
join checks as c using (ccn)
where not h.federally_run
group by h.ccn, h.name, h.city, h.hospital_type, h.ownership, h.price_file_status
