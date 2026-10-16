# The data bucket: raw price files as downloaded (raw/) and parsed Parquet (parquet/).
#
# Everything in it can be rebuilt by rerunning the pipeline, so unlike the state bucket
# it has no versioning and force_destroy is on: `terraform destroy` empties and deletes it.

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "data" {
  bucket        = "${var.project}-data-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced" # ACLs off; access only through IAM
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # S3-managed keys: free, unlike a KMS key
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.data]
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # Raw files are only needed until they're parsed and checked; hospitals' own sites
  # are the long-term copy. parquet/ has no rule, so it is kept.
  rule {
    id     = "expire-raw-after-7-days"
    status = "Enabled"
    filter {
      prefix = "raw/"
    }
    expiration {
      days = 7
    }
  }

  # A download cut off midway leaves invisible upload parts that are still billed.
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

output "data_bucket" {
  description = "Set as DATA_BUCKET for the downloader."
  value       = aws_s3_bucket.data.bucket
}
