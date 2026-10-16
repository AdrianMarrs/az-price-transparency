# The serving table: precomputed answers for the site. Key design in docs/03-cloud.md.
#
#   PK HOSPITAL#<ccn>   SK SERVICE#<service_key>   one hospital x service (prices per plan)
#   PK HOSPITAL#<ccn>   SK PROFILE                 one hospital (compliance, shoppable summary)
#   by_service index: GSI1PK SERVICE#<service_key>, GSI1SK HOSPITAL#<ccn> (compare hospitals)
#
# Everything in it is rebuilt from Postgres by the export, so there is no point-in-time
# recovery (billed per GB) and no deletion protection: `terraform destroy` removes it.

resource "aws_dynamodb_table" "prices" {
  name         = "${var.project}-prices"
  billing_mode = "PAY_PER_REQUEST" # on-demand: no capacity to plan, billed per request
  hash_key     = "PK"
  range_key    = "SK"

  # Only key attributes are declared; DynamoDB is schemaless for everything else.
  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
  attribute {
    name = "GSI1PK"
    type = "S"
  }
  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # Sparse: only hospital x service items carry GSI1PK, so profiles stay out of it.
  # ALL projection because the compare page needs the prices, not just the keys.
  global_secondary_index {
    name            = "by_service"
    projection_type = "ALL"
    key_schema {
      attribute_name = "GSI1PK"
      key_type       = "HASH" # partition key
    }
    key_schema {
      attribute_name = "GSI1SK"
      key_type       = "RANGE" # sort key
    }
  }

  # Encryption at rest is always on; this default uses an AWS-owned key at no cost.
  point_in_time_recovery {
    enabled = false
  }
}

output "prices_table" {
  description = "DynamoDB table the export writes and the API reads."
  value       = aws_dynamodb_table.prices.name
}
