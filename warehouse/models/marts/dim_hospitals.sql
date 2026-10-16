-- One row per hospital in scope, with where its price file was found.

select
    h.ccn,
    h.name,
    h.address,
    h.city,
    h.state,
    h.zip,
    h.county,
    h.hospital_type,
    h.ownership,
    h.federally_run,
    s.status as price_file_status,
    s.source_page_url,
    s.mrf_url
from {{ ref('hospitals') }} as h
left join {{ ref('hospital_sources') }} as s using (ccn)
