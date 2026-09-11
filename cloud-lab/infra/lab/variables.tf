variable "workload_account_id" {
  type = string
}

variable "security_account_id" {
  type = string
}

variable "region" {
  type    = string
  default = "ap-northeast-2"
}

variable "project" {
  type    = string
  default = "ea"
}

variable "operation_mode" {
  description = "setup: NAT 활성 / operate: SSM endpoints 활성 / idle: 둘 다 비활성"
  type        = string
  default     = "setup"

  validation {
    condition     = contains(["setup", "operate", "idle"], var.operation_mode)
    error_message = "operation_mode는 setup, operate, idle 중 하나"
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.60.0.0/16"
}

variable "az_primary" {
  type    = string
  default = "ap-northeast-2a"
}

variable "az_secondary" {
  type    = string
  default = "ap-northeast-2c"
}

variable "ami_id" {
  description = "Ubuntu 24.04 LTS AMI ID"
  type        = string
}

variable "key_name" {
  description = "SSH 키 페어 이름 (비상 접속용, SSM 우선)"
  type        = string
  default     = ""
}

variable "kms_workload_ebs_arn" {
  description = "Foundation에서 생성한 workload EBS KMS 키 ARN"
  type        = string
}

variable "s3_alb_logs_bucket" {
  description = "ALB 로그 S3 버킷 ID"
  type        = string
}

variable "common_tags" {
  type = map(string)
  default = {
    Project     = "evidence-atlas"
    Environment = "lab"
    ManagedBy   = "opentofu"
  }
}

variable "wordpress_version" {
  description = "Exact normal-portal release selected and reviewed before deployment."
  type        = string
  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.wordpress_version))
    error_message = "Use an exact WordPress patch release."
  }
}
variable "wordpress_sha256" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{64}$", var.wordpress_sha256))
    error_message = "Provide the SHA-256 of the selected official WordPress archive."
  }
}
variable "elastic_version" {
  type    = string
  default = "8.17.0"
  validation {
    condition     = can(regex("^8\\.[0-9]+\\.[0-9]+$", var.elastic_version))
    error_message = "Provide an exact compatible Elastic 8.x patch release."
  }
}
