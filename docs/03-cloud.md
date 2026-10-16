# 03 · Cloud and serving layer

Phase 3 puts precomputed answers in DynamoDB behind a Lambda API, with a React site, all defined in Terraform. Postgres stays the system of record; DynamoDB only holds what the site reads.

## DynamoDB key design

Written before any code, because in DynamoDB the keys are the queries: it fetches by key fast and does nothing else well (no joins, no ad-hoc filters, no text search). So the design starts from the questions the site asks.

### Decisions

- **All of Arizona**, all 13,243 services, with every plan's price. (Pima County stays the headline in the write-ups.)
- **One item per hospital × service**, not per price row: 338,697 items instead of 14.6M. DynamoDB bills per write, so this is about $2 for a full export instead of about $18, and the site always shows a hospital's prices for a service together anyway.
- **Hospitals are keyed by CCN**, not NPI: CCN is the project's hospital id everywhere else, and one hospital has up to dozens of NPIs.
- **On-demand capacity**: no capacity planning, pay per request, and the traffic is tiny.

### Access patterns

| Question | Endpoint | How it's answered |
| --- | --- | --- |
| Find a service ("knee mri") | `GET /services?q=` | Not DynamoDB. The service list (code, description, shoppable flag; about 1 MB) is a static JSON file served by CloudFront and searched in the browser. |
| Compare hospitals for one service | `GET /services/{code}/prices?payer=` | One `Query` on the index `by_service`: `GSI1PK = SERVICE#<code>`, every hospital that prices it (up to 69). The payer filter is applied in the Lambda. Hospital names and scores come from one `BatchGetItem` of the `PROFILE` items. |
| One hospital | `GET /providers/{ccn}` | `GetItem` of `HOSPITAL#<ccn>` / `PROFILE`: name, address, compliance score and rule results, and a summary of its CMS shoppable services. Its full service list pages through `Query PK = HOSPITAL#<ccn>, SK begins_with SERVICE#`. |
| One hospital, one service | (used by both pages) | `GetItem` of `HOSPITAL#<ccn>` / `SERVICE#<code>`. |

### Items

| Item | PK | SK | GSI1PK | GSI1SK | Attributes |
| --- | --- | --- | --- | --- | --- |
| Hospital × service | `HOSPITAL#<ccn>` | `SERVICE#<code>` | `SERVICE#<code>` | `HOSPITAL#<ccn>` | description, cash and gross prices, `prices`: one entry per payer × plan × setting × price type with payer group, market, methodology, median amount and row count; `content_hash` |
| Hospital profile | `HOSPITAL#<ccn>` | `PROFILE` | — | — | name, city, county, type, compliance score and rules, shoppable-service summary, `content_hash` |

`<code>` is the warehouse `service_key` (e.g. `CPT/HCPCS:73721`). Profile items leave the GSI keys out, so they don't appear in the index (a *sparse* index).

**Why a GSI rather than writing each item twice.** The two price questions read the same item from two directions (hospital first, or service first). A global secondary index is a copy of the table that DynamoDB keeps in sync under different keys, so the exporter writes each item once. It costs the same writes as a second copy would, but there's no way for the two copies to disagree. The index projects all attributes, because the compare page needs the prices.

**Why names and scores aren't copied into every price item.** A hospital's score changes when its file changes, and copying it into its ~5,000 price items would mean rewriting all of them. One `BatchGetItem` of up to 69 profiles per compare request is cheaper.

### Sizes (measured 2026-10-16)

| | |
| --- | ---: |
| Hospital × service items | 338,697 |
| Average item | 4.7 KB |
| 99th percentile | 16 KB |
| Largest | 134 KB (876 price entries) |
| Total | about 1.6 GB |

The item limit is 400 KB, so the largest is at a third of it. The exporter fails loudly on any item over 350 KB rather than truncating it. A compare query reads up to 69 items, about 320 KB on average, which is under the 1 MB `Query` page limit, so most compare requests take one page.

### Cost

On-demand writes cost one write unit per KB, and the index costs the same again. A full export is about 3.4M write units, roughly $2. Storage is inside the 25 GB free tier.

To keep weekly runs near zero, the export is idempotent and incremental. Each item's JSON is built deterministically and hashed. The exporter keeps the last exported hash per key in Postgres, writes only items whose hash changed, and deletes items that are no longer produced. A rerun with the same input writes nothing.

### Not in DynamoDB

- **Pipeline state** (the plan's `FILE#<checksum>` pattern): already in Postgres `raw.source_files` and in Dagster, so it isn't duplicated here.
- **Statewide and national statistics:** `marts.price_summary` stays in Postgres; the site shows per-hospital prices.

## Terraform

Two stacks, both in `infra/`:

- **`bootstrap/`**: the S3 bucket that stores Terraform state: versioned (every state write kept, old versions expire after 90 days), encrypted with S3-managed keys, public access blocked, HTTPS only, and protected from `destroy`. Its first apply had to use local state, since a backend can't live in a bucket that doesn't exist yet; its state was then moved into the bucket it created (`bootstrap/terraform.tfstate`) with `terraform init -migrate-state`, so no state lives only on one machine. Tearing it down means moving the state back to local first.
- **`main/`**: everything else. It keeps its state in that bucket, locked with S3's native lock file (`use_lockfile`, Terraform 1.10+), which replaces the DynamoDB lock table older setups needed. `default_tags` on the provider tags every resource `Project = az-price-transparency`, so the project's resources and costs can be found and torn down together.

Changes are applied only from a saved plan that has been read first:

```
$env:AWS_PROFILE = "az-price"
cd infra/main
terraform init '-backend-config=backend.hcl'     # copy backend.hcl.example (bootstrap uses ../main/backend.hcl); quotes needed in PowerShell 5.1
terraform plan '-out=main.tfplan'
terraform apply main.tfplan
```

CI checks formatting and validates both stacks on every push, without AWS credentials.

Teardown was tested early, on the data bucket: apply, destroy (bucket confirmed gone), apply, then a plan showing no drift.

## Data bucket

`az-price-transparency-data-<account id>` (`infra/main/data_bucket.tf`): public access blocked, S3-managed encryption, HTTPS only. Its contents can all be rebuilt, so it has no versioning and `force_destroy` lets `terraform destroy` remove it.

| Prefix | What | Kept |
| --- | --- | --- |
| `raw/<yyyy-mm-dd>/` | Price files as downloaded, gzip-compressed | 7 days (lifecycle rule); the hospitals' sites are the long-term copy |
| `parquet/` | Parsed prices, one file per hospital | Until replaced |

The pipeline writes to local disk as before (the parser and loader read it) and, when `DATA_BUCKET` is set, copies each new raw file and each Parquet file to the bucket (`ingest/storage.py`). The raw file's S3 location is recorded in `raw.source_files.s3_uri`. A failed upload is reported but never fails the download or parse. Without `DATA_BUCKET`, as in tests and CI, nothing is uploaded.

```
$env:AWS_PROFILE = "az-price"
$env:DATA_BUCKET = "az-price-transparency-data-<account id>"   # terraform -chdir=infra/main output data_bucket
uv run dagster dev -m orchestration.definitions
```

`aws login` credentials need botocore's CRT extension, so the dependency is `boto3[crt]`.

## DynamoDB table

`az-price-transparency-prices` (`infra/main/dynamodb.tf`): on-demand, with the `by_service` index, as designed above. No point-in-time recovery (billed per GB; the export rebuilds it) and no deletion protection, so `terraform destroy` still removes everything. Empty until the export step.

## Blocked: GitHub Actions to AWS (OIDC)

The deploy role is written (local branch `oidc-blocked`: `infra/bootstrap/github_oidc.tf` and `.github/workflows/deploy.yml`) but can't be applied: a service control policy in the AWS Organization this account belongs to denies every IAM OpenID Connect provider action, even listing them. It has to be changed from the organization's management account. Until then, Terraform is applied from a laptop.
