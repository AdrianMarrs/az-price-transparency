"""Parse a hospital's cms-hpt.txt file.

CMS requires each hospital to post a cms-hpt.txt file at the root of its website
that points to its machine-readable price file(s). The file is a set of
"key: value" lines, one block per location:

    location-name: Example Hospital
    source-page-url: https://example.org/price-transparency
    mrf-url: https://example.org/files/123456789_example-hospital_standardcharges.csv
    contact-name: Jane Doe
    contact-email: pricing@example.org

Blocks are usually separated by blank lines, but some files put a blank line between
every field (Valleywise), so a new block starts at each location-name line instead.
"""


def parse_cms_hpt(text: str) -> list[dict[str, str]]:
    """Return one dict per location, with keys lowercased.

    Lines without a colon are ignored. Only the first colon splits key from value, so
    URLs (which contain colons) are kept intact. A repeated key also starts a new block,
    for files that list locations without location-name lines.
    """
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if current and (key == "location-name" or key in current):
            entries.append(current)
            current = {}
        current[key] = value

    if current:
        entries.append(current)
    return entries
