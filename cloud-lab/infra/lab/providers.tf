terraform {
  required_version = ">= 1.9.0"

  required_providers {
    tls = {
      source  = "registry.opentofu.org/hashicorp/tls"
      version = "= 4.0.6"
    }
    random = {
      source  = "registry.opentofu.org/hashicorp/random"
      version = "= 3.6.3"
    }
    aws = {
      source  = "registry.opentofu.org/hashicorp/aws"
      version = "= 5.82.0"
    }
  }

  backend "s3" {
    key            = "lab/terraform.tfstate"
    region         = "ap-northeast-2"
    encrypt        = true
    dynamodb_table = "ea-tofu-lock"
  }
}

provider "aws" {
  allowed_account_ids = [var.workload_account_id]
  region              = var.region

  assume_role {
    role_arn = "arn:aws:iam::${var.workload_account_id}:role/EADeployRole"
  }

  default_tags {
    tags = var.common_tags
  }
}
