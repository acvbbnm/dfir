terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "registry.opentofu.org/hashicorp/aws"
      version = "= 5.82.0"
    }
  }

}

provider "aws" {
  alias               = "security"
  allowed_account_ids = [var.security_account_id]
  region              = var.region

  default_tags {
    tags = var.common_tags
  }
}

provider "aws" {
  alias               = "workload"
  allowed_account_ids = [var.workload_account_id]
  region              = var.region

  assume_role {
    role_arn = "arn:aws:iam::${var.workload_account_id}:role/EADeployRole"
  }

  default_tags {
    tags = var.common_tags
  }
}
