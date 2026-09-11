variable "role" {
  type = string
  validation {
    condition     = contains(["web", "app", "soc"], var.role)
    error_message = "role must be web, app or soc."
  }
}

variable "environment" {
  description = "Non-secret installation settings only; credentials are fetched on the host."
  type        = map(string)
  default     = {}
  validation {
    condition     = alltrue([for k in keys(var.environment) : can(regex("^[A-Z][A-Z0-9_]*$", k))])
    error_message = "Environment names must be uppercase shell identifiers."
  }
}

locals {
  root    = "${path.module}/../../.."
  scripts = concat(["base.sh", "${var.role}.sh", "agent.sh", "velociraptor.sh"], var.role == "app" ? ["configure_wordpress.py"] : var.role == "soc" ? ["soc_disk.py"] : [])
  assets  = var.role == "web" ? ["nginx/default.conf", "suricata/suricata-ea.yaml", "suricata/local.rules"] : var.role == "app" ? ["wordpress/wp-config.php.tpl", "wordpress/mu-plugins/ea-audit.php"] : []
  files = concat(
    [for name in local.scripts : {
      path        = "/opt/ea-bootstrap/${name}"
      permissions = "0700"
      owner       = "root:root"
      encoding    = "b64"
      content     = base64encode(replace(file("${local.root}/bootstrap/${name}"), "\r\n", "\n"))
    }],
    [for name in local.assets : {
      path        = "/opt/ea-bootstrap/application/${name}"
      permissions = "0644"
      owner       = "root:root"
      encoding    = "b64"
      content     = base64encode(replace(file("${local.root}/application/${name}"), "\r\n", "\n"))
    }],
    [{
      path        = "/opt/ea-bootstrap/environment.sh"
      permissions = "0600"
      owner       = "root:root"
      encoding    = "b64"
      content     = base64encode(format("%s\n", join("\n", [for k, v in var.environment : "export ${k}='${replace(v, "'", "'\"'\"'")}'"])))
    }]
  )
  cloud_config = "#cloud-config\n${jsonencode({
    write_files = local.files
    runcmd      = [["/bin/bash", "-e", "/opt/ea-bootstrap/${var.role}.sh"]]
  })}\n"
}

output "cloud_config" {
  value = local.cloud_config
}

output "user_data_base64" {
  value = base64gzip(local.cloud_config)
  precondition {
    condition     = length(base64gzip(local.cloud_config)) <= 21844
    error_message = "Compressed EC2 user data exceeds the 16 KiB limit; move assets to a versioned package."
  }
}
