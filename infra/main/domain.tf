# The site's own name (clearhealthcareprices.com), registered and served by Cloudflare DNS.
# CloudFront only accepts a certificate from ACM in us-east-1, whatever the stack's region.
#
# Two applies, because the certificate has to be proved before CloudFront can use it:
#   1. set site_domain: creates the certificate; add the validation_records output to
#      Cloudflare as DNS-only CNAMEs and wait for ACM to issue it (a few minutes)
#   2. set site_domain_live = true: CloudFront answers for the name and www redirects to it;
#      then point the name and www at site_url's host in Cloudflare (DNS-only CNAMEs)

provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "main"
    }
  }
}

locals {
  site_aliases = var.site_domain == null ? [] : [var.site_domain, "www.${var.site_domain}"]
  site_live    = var.site_domain != null && var.site_domain_live
}

resource "aws_acm_certificate" "site" {
  count    = var.site_domain == null ? 0 : 1
  provider = aws.us_east_1

  domain_name               = var.site_domain
  subject_alternative_names = ["www.${var.site_domain}"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Waits until ACM has seen the validation records and issued the certificate.
resource "aws_acm_certificate_validation" "site" {
  count           = local.site_live ? 1 : 0
  provider        = aws.us_east_1
  certificate_arn = aws_acm_certificate.site[0].arn
}

output "site_domain_validation_records" {
  description = "Add these to Cloudflare as CNAMEs, proxy off (DNS only)."
  value = var.site_domain == null ? [] : [
    for o in aws_acm_certificate.site[0].domain_validation_options : {
      name  = o.resource_record_name
      value = o.resource_record_value
    }
  ]
}
