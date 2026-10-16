variable "project" {
  description = "Name used for the bucket and the Project tag."
  type        = string
  default     = "az-price-transparency"
}

variable "region" {
  description = "AWS region for the state bucket."
  type        = string
  default     = "us-east-2"
}
