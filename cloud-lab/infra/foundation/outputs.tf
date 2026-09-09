output "kms_workload_ebs_arn" {
  description = "Workload EBS 암호화 KMS 키 ARN"
  value       = aws_kms_key.workload_ebs.arn
}

output "kms_evidence_s3_arn" {
  description = "증거 S3 암호화 KMS 키 ARN"
  value       = aws_kms_key.evidence_s3.arn
}

output "kms_evidence_ebs_arn" {
  description = "증거 EBS 스냅샷 KMS 키 ARN"
  value       = aws_kms_key.evidence_ebs.arn
}

output "s3_evidence_staging_bucket" {
  description = "증거 staging S3 버킷 이름"
  value       = aws_s3_bucket.evidence_staging.id
}

output "s3_evidence_staging_arn" {
  value = aws_s3_bucket.evidence_staging.arn
}

output "s3_evidence_final_bucket" {
  description = "증거 final S3 버킷 이름"
  value       = aws_s3_bucket.evidence_final.id
}

output "s3_evidence_final_arn" {
  value = aws_s3_bucket.evidence_final.arn
}

output "s3_cloudtrail_bucket" {
  description = "CloudTrail S3 버킷 이름"
  value       = aws_s3_bucket.cloudtrail.id
}

output "s3_waf_logs_bucket" {
  value = aws_s3_bucket.waf_logs.id
}

output "s3_alb_logs_bucket" {
  value = aws_s3_bucket.alb_logs.id
}

output "s3_flow_logs_bucket" {
  value = aws_s3_bucket.flow_logs.id
}

output "cloudtrail_arn" {
  value = aws_cloudtrail.main.arn
}

output "budget_sns_topic_arn" {
  value = aws_sns_topic.budget_alerts.arn
}
