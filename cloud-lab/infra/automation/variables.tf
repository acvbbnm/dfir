variable "security_account_id" {
  type = string
}

variable "collection_enabled" {
  description = "Enable automatic collection after the generated collector and cross-account upload contract pass D-3."
  type        = bool
  default     = false
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

variable "audit_extra_regions" {
  description = "Additional experiment event regions beyond primary and us-east-1."
  type        = list(string)
  default     = []
  validation {
    condition     = length(var.audit_extra_regions) <= 3 && alltrue([for region in var.audit_extra_regions : can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]$", region))])
    error_message = "Select at most three explicit AWS regions."
  }
}
