variable "project" {
  description = "Name prefix for resources and the Project tag."
  type        = string
  default     = "az-price-transparency"
}

variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "us-east-2"
}

variable "alert_email" {
  description = "Where budget alerts are emailed. Not committed: set TF_VAR_alert_email."
  type        = string
}

variable "insurer_schedule_enabled" {
  description = "Run the insurer pipeline monthly. Off: the data stays as the initial pass left it until a refresh is turned on (October 2026)."
  type        = bool
  default     = false
}

variable "site_domain" {
  description = "The site's own domain (registered at Cloudflare, October 2026); null serves only the CloudFront name."
  type        = string
  default     = "clearhealthcareprices.com"
}

variable "site_domain_live" {
  description = "Serve the site at site_domain. Set once its certificate is issued (see domain.tf)."
  type        = bool
  default     = true # certificate issued October 2026
}
