# The React site (web/): built files in a private bucket, served only through CloudFront.
# The bucket isn't a public website; CloudFront reads it with Origin Access Control (OAC),
# so the files can't be fetched from S3 directly. Deploy: scripts/deploy_site.py.

resource "aws_s3_bucket" "site" {
  bucket        = "${var.project}-site-${data.aws_caller_identity.current.account_id}"
  force_destroy = true # rebuilt from web/ by every deploy
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.project}-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Only this distribution may read the bucket, and only over HTTPS.
resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontReadsSite"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.site.arn, "${aws_s3_bucket.site.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.site]
}

# Security headers (HSTS, nosniff, frame denial, referrer policy) plus a content security
# policy: scripts and styles only from the site itself, data only from the API.
resource "aws_cloudfront_response_headers_policy" "site" {
  name = "${var.project}-site"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
    content_security_policy {
      content_security_policy = join("; ", [
        "default-src 'self'",
        "connect-src 'self' https://${aws_cloudfront_distribution.api.domain_name}",
        "img-src 'self' data:",
        "style-src 'self'",
        "script-src 'self'",
        "frame-ancestors 'none'",
      ])
      override = true
    }
  }
}

# Pre-rendered pages are folders with an index.html (web/react-router.config.ts); this maps
# their URLs to those files. Free tier: 2 million invocations a month.
resource "aws_cloudfront_function" "site_router" {
  name    = "${var.project}-site-router"
  runtime = "cloudfront-js-2.0"
  comment = "Map page URLs to pre-rendered index.html files"
  publish = true
  code    = templatefile("${path.module}/site_router.js", { apex = local.site_live ? var.site_domain : "" })
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "${var.project} site"
  default_root_object = "index.html"
  price_class         = "PriceClass_100"
  is_ipv6_enabled     = true
  aliases             = local.site_live ? local.site_aliases : []

  origin {
    origin_id                = "site"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id           = "site"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6" # AWS managed: CachingOptimized
    response_headers_policy_id = aws_cloudfront_response_headers_policy.site.id
    compress                   = true

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.site_router.arn
    }
  }

  # A page that wasn't pre-rendered: S3 says 403 (no such object; the bucket isn't listable),
  # and the app shell renders the page in the browser instead. A path that really doesn't
  # exist gets the site's own 404 page from the app.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/__spa-fallback.html"
    error_caching_min_ttl = 60
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/__spa-fallback.html"
    error_caching_min_ttl = 60
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  # The CloudFront name until the site's own domain is live (domain.tf).
  viewer_certificate {
    cloudfront_default_certificate = local.site_live ? null : true
    acm_certificate_arn            = local.site_live ? aws_acm_certificate_validation.site[0].certificate_arn : null
    ssl_support_method             = local.site_live ? "sni-only" : null
    minimum_protocol_version       = local.site_live ? "TLSv1.2_2021" : null
  }
}

output "site_bucket" {
  description = "Where scripts/deploy_site.py uploads web/build/client."
  value       = aws_s3_bucket.site.bucket
}

output "site_url" {
  value = "https://${local.site_live ? var.site_domain : aws_cloudfront_distribution.site.domain_name}"
}

output "site_distribution_id" {
  value = aws_cloudfront_distribution.site.id
}
