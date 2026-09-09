terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "registry.opentofu.org/hashicorp/aws"
      version = "~> 5.82"
    }
  }

  backend "s3" {
    bucket         = "ea-tofu-state"
    key            = "automation/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    dynamodb_table = "ea-tofu-lock"
  }
}

provider "aws" {
  alias  = "security"
  region = var.region

  default_tags {
    tags = var.common_tags
  }
}

provider "aws" {
  alias  = "workload"
  region = var.region

  assume_role {
    role_arn = "arn:aws:iam::${var.workload_account_id}:role/EADeployRole"
  }

  default_tags {
    tags = var.common_tags
  }
}
