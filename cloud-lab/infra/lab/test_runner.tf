variable "enable_test_runner" {
  description = "Temporary SSM-only client in test-a for internal ALB checks. Disable after the session."
  type        = bool
  default     = false
}
resource "aws_iam_role" "test_runner" {
  count              = var.enable_test_runner ? 1 : 0
  name               = "${var.project}-test-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}
resource "aws_iam_role_policy_attachment" "test_ssm" {
  count      = var.enable_test_runner ? 1 : 0
  role       = aws_iam_role.test_runner[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_instance_profile" "test_runner" {
  count = var.enable_test_runner ? 1 : 0
  name  = "${var.project}-test-profile"
  role  = aws_iam_role.test_runner[0].name
}
locals {
  test_runner_cloud_config = "#cloud-config\n${jsonencode({
    write_files = [
      { path = "/opt/ea/scenario_runner.py", permissions = "0755", content = file("${path.module}/../../scripts/scenario_runner.py") },
      { path = "/opt/ea/alb.pem", permissions = "0644", content = tls_self_signed_cert.alb.cert_pem },
      { path = "/opt/ea/target.txt", permissions = "0644", content = "https://${aws_lb.main.dns_name}" }
    ]
  })}"
}
resource "aws_instance" "test_runner" {
  count                       = var.enable_test_runner ? 1 : 0
  ami                         = var.ami_id
  instance_type               = "t3.small"
  subnet_id                   = aws_subnet.this["test-a"].id
  associate_public_ip_address = false
  iam_instance_profile        = aws_iam_instance_profile.test_runner[0].name
  vpc_security_group_ids      = [aws_security_group.ssm.id, aws_security_group.base.id]
  user_data_base64            = base64gzip(local.test_runner_cloud_config)
  user_data_replace_on_change = true
  depends_on                  = [aws_iam_role_policy_attachment.test_ssm, aws_route_table_association.private]
  root_block_device {
    volume_size = 12
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_workload_ebs_arn
  }
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }
  tags = { Name = "${var.project}-test", Role = "test" }
}
output "test_instance_id" { value = try(aws_instance.test_runner[0].id, null) }
