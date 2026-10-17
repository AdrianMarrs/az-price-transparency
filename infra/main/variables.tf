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
  description = "Run the insurer pipeline monthly. Off until a manual run has been checked."
  type        = bool
  default     = false
}
