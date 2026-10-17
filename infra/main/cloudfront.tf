# CloudFront in front of the API: each distinct question is answered by the Lambda once,
# then served from the edge for a day (the handler sends s-maxage=86400). The weekly export
# clears it (CLOUDFRONT_DISTRIBUTION_ID). DynamoDB is already fast, so this is about
# latency to the viewer and never paying for the same answer twice, not database load.

resource "aws_cloudfront_cache_policy" "api" {
  name        = "${var.project}-api"
  comment     = "Cache API answers by path and the q, payer and market parameters"
  min_ttl     = 0
  default_ttl = 86400 # used only if a response has no Cache-Control
  max_ttl     = 86400

  parameters_in_cache_key_and_forwarded_to_origin {
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "whitelist" # anything else (?x=random) can't bust the cache
      query_strings {
        items = ["q", "payer", "market"]
      }
    }
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
  }
}

resource "aws_cloudfront_distribution" "api" {
  enabled         = true
  comment         = "${var.project} API"
  price_class     = "PriceClass_100" # North America and Europe edges: the cheapest class
  is_ipv6_enabled = true

  origin {
    origin_id   = "api"
    domain_name = trimprefix(aws_apigatewayv2_api.api.api_endpoint, "https://")
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "api"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = aws_cloudfront_cache_policy.api.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true # *.cloudfront.net; a custom domain can come later
  }
}

output "api_cdn_url" {
  description = "The API through CloudFront; what the site and MCP server should call."
  value       = "https://${aws_cloudfront_distribution.api.domain_name}"
}

output "cloudfront_distribution_id" {
  description = "Set as CLOUDFRONT_DISTRIBUTION_ID so the export can clear the cache."
  value       = aws_cloudfront_distribution.api.id
}
