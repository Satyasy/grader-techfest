output "alb_dns_name" {
  description = "Public URL ALB"
  value       = aws_lb.main.dns_name
}

output "rds_endpoint" {
  description = "Endpoint MySQL RDS"
  value       = aws_db_instance.mysql.address
}

output "s3_bucket_name" {
  description = "Nama bucket S3"
  value       = aws_s3_bucket.app_storage.id
}
