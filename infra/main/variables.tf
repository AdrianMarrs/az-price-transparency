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
