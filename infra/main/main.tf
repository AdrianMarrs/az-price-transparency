# Everything the project runs in AWS. Empty for now: Phase 3 adds the data bucket,
# DynamoDB table, Lambda API and site here, one step at a time.

provider "aws" {
  region = var.region

  # Every resource gets these tags, so the project's resources (and costs) can be found
  # and torn down together.
  default_tags {
    tags = {
      Project   = var.project
      ManagedBy = "terraform"
      Stack     = "main"
    }
  }
}
