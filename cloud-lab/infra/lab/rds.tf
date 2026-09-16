resource "aws_db_subnet_group" "main" {
  name = "${var.project}-db-subnet"
  subnet_ids = [
    aws_subnet.this["db-a"].id,
    aws_subnet.this["db-c"].id
  ]

  tags = { Name = "${var.project}-db-subnet" }
}

resource "aws_db_parameter_group" "mysql84" {
  name   = "${var.project}-mysql84"
  family = "mysql8.4"

  parameter {
    name  = "require_secure_transport"
    value = "ON"
  }

  parameter {
    name  = "log_output"
    value = "FILE"
  }

  parameter {
    name  = "slow_query_log"
    value = "1"
  }

  parameter {
    name  = "long_query_time"
    value = "1"
  }

  parameter {
    name  = "general_log"
    value = "0"
  }

  parameter {
    name  = "log_error_verbosity"
    value = "3"
  }

  tags = { Name = "${var.project}-mysql84" }
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project}-mysql"
  engine         = "mysql"
  engine_version = "8.4"
  instance_class = "db.t4g.micro"

  allocated_storage     = 20
  max_allocated_storage = 30
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  parameter_group_name   = aws_db_parameter_group.mysql84.name

  db_name  = "wordpress"
  username = "admin"
  password = random_password.db_master.result

  multi_az                  = false
  publicly_accessible       = false
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-mysql-final-${random_id.database_run.hex}"
  backup_retention_period   = 7
  copy_tags_to_snapshot     = true
  deletion_protection       = false

  enabled_cloudwatch_logs_exports = ["error", "slowquery"]

  tags = { Name = "${var.project}-mysql" }
}

resource "random_password" "db_master" {
  length           = 24
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_secretsmanager_secret" "db_credentials" {
  name = "${var.project}/db/master"
  tags = { Name = "${var.project}-db-secret" }
}

resource "aws_secretsmanager_secret_version" "db_credentials" {
  secret_id = aws_secretsmanager_secret.db_credentials.id
  secret_string = jsonencode({
    username = aws_db_instance.main.username
    password = random_password.db_master.result
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
  })
}


# Application credentials are distinct from the administrator secret.
# An operator provisions this user with privileges only on wordpress.* in B-3-2.
resource "random_password" "wordpress" {
  length  = 32
  special = false
}
resource "aws_secretsmanager_secret" "wordpress" {
  name = "${var.project}/db/wordpress"
}
resource "aws_secretsmanager_secret_version" "wordpress" {
  secret_id = aws_secretsmanager_secret.wordpress.id
  secret_string = jsonencode({
    username = "wordpress_user"
    password = random_password.wordpress.result
    host     = aws_db_instance.main.address
    port     = aws_db_instance.main.port
    dbname   = aws_db_instance.main.db_name
  })
}

resource "random_password" "dvwa" {
  length  = 32
  special = false
}
resource "aws_secretsmanager_secret" "dvwa" { name = "${var.project}/db/dvwa" }
resource "aws_secretsmanager_secret_version" "dvwa" {
  secret_id = aws_secretsmanager_secret.dvwa.id
  secret_string = jsonencode({ username = "dvwa_user", password = random_password.dvwa.result,
  host = aws_db_instance.main.address, port = aws_db_instance.main.port, dbname = "dvwa" })
}
resource "random_id" "database_run" { byte_length = 4 }
