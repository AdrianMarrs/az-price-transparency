"""Parse a hospital's cms-hpt.txt file.

CMS requires each hospital to post a cms-hpt.txt file at the root of its website
that points to its machine-readable price file(s). The file is a set of
"key: value" lines, one block per location, with blocks separated by blank lines:

    location-name: Example Hospital
    source-page-url: https://example.org/price-transparency
    mrf-url: https://example.org/files/123456789_example-hospital_standardcharges.csv
    contact-name: Jane Doe
    contact-email: pricing@example.org
"""


def parse_cms_hpt(text: str) -> list[dict[str, str]]:
    """Return one dict per location block, with keys lowercased.

    Lines without a colon are ignored. Only the first colon splits key from
    value, so URLs (which contain colons) are kept intact.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                entries.append(current)
                current = {}
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        current[key.strip().lower()] = value.strip()

    if current:
        entries.append(current)
    return entries
