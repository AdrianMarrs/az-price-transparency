terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # State lives in the bootstrap bucket. The bucket name includes the account id, so it
  # is passed at init rather than written here:
  #   terraform init -backend-config="bucket=<infra/bootstrap output state_bucket>"
  backend "s3" {
    key          = "main/terraform.tfstate"
    region       = "us-east-2"
    encrypt      = true
    use_lockfile = true # S3 native locking: no DynamoDB lock table needed
  }
}
