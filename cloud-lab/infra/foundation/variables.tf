variable "security_account_id" {
  description = "Security/Evidence AWS 계정 ID"
  type        = string
}

variable "workload_account_id" {
  description = "Workload AWS 계정 ID"
  type        = string
}

variable "region" {
  description = "AWS 리전"
  type        = string
  default     = "ap-northeast-2"
}

variable "project" {
  description = "프로젝트 식별자 (리소스 이름 접두사)"
  type        = string
  default     = "ea"
}

variable "environment" {
  description = "환경 태그"
  type        = string
  default     = "lab"
}

variable "budget_warning_usd" {
  description = "예산 경고 임계값 (USD)"
  type        = number
  default     = 200
}

variable "budget_critical_usd" {
  description = "예산 위험 임계값 (USD)"
  type        = number
  default     = 250
}

variable "budget_limit_usd" {
  description = "예산 상한 (USD)"
  type        = number
  default     = 300
}

variable "budget_notification_email" {
  description = "예산 알림 수신 이메일"
  type        = string
}

variable "common_tags" {
  description = "모든 리소스에 부여할 공통 태그"
  type        = map(string)
  default = {
    Project     = "evidence-atlas"
    Environment = "lab"
    ManagedBy   = "opentofu"
  }
}
