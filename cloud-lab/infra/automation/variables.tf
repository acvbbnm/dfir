variable "security_account_id" {
  type = string
}

variable "workload_account_id" {
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

variable "kms_evidence_s3_arn" {
  description = "Foundation 증거 S3 KMS 키 ARN"
  type        = string
}

variable "s3_evidence_staging_arn" {
  type = string
}

variable "s3_evidence_staging_bucket" {
  type = string
}

variable "s3_evidence_final_arn" {
  type = string
}

variable "s3_evidence_final_bucket" {
  type = string
}

variable "common_tags" {
  type = map(string)
  default = {
    Project     = "evidence-atlas"
    Environment = "lab"
    ManagedBy   = "opentofu"
  }
}
