variable "aws_region" {
  description = "Region AWS untuk testing"
  type        = string
  default     = "us-east-1"
}

variable "vpc_cidr" {
  description = "CIDR block utama VPC"
  type        = string
  default     = "10.20.0.0/16"
}

variable "db_password" {
  description = "Password RDS MySQL"
  type        = string
  default     = "Techfest2026SecurePass!"
  sensitive   = true
}
