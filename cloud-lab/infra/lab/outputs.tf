output "vpc_id" {
  value = aws_vpc.main.id
}

output "subnet_ids" {
  value = { for k, v in aws_subnet.this : k => v.id }
}

output "web_instance_id" {
  value = aws_instance.web.id
}

output "web_private_ip" {
  value = aws_instance.web.private_ip
}

output "app_instance_id" {
  value = aws_instance.app.id
}

output "app_private_ip" {
  value = aws_instance.app.private_ip
}

output "soc_instance_id" {
  value = aws_instance.soc.id
}

output "soc_private_ip" {
  value = aws_instance.soc.private_ip
}

output "rds_endpoint" {
  value = aws_db_instance.main.endpoint
}

output "rds_address" {
  value = aws_db_instance.main.address
}

output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "alb_arn" {
  value = aws_lb.main.arn
}

output "waf_web_acl_arn" {
  value = var.enable_aws_waf ? aws_wafv2_web_acl.main[0].arn : null
}

output "sg_isolation_id" {
  description = "격리 SG — 대응 시 교체용"
  value       = aws_security_group.isolation.id
}

output "db_secret_arn" {
  value = aws_secretsmanager_secret.db_credentials.arn
}

output "wordpress_secret_arn" { value = aws_secretsmanager_secret.wordpress.arn }
output "soc_data_volume_id" { value = aws_ebs_volume.soc_data.id }

output "dvwa_secret_arn" { value = aws_secretsmanager_secret.dvwa.arn }

output "rds_identifier" { value = aws_db_instance.main.id }
output "resolver_log_group" { value = aws_cloudwatch_log_group.resolver.name }
