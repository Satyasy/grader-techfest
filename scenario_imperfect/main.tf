terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Ambil 2 Availability Zone pertama di region
data "aws_availability_zones" "available" {
  state = "available"
}

# Ambil Ubuntu 24.04 LTS AMI terbaru
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# =========================================================================
# 1. NETWORKING (VPC, Subnets, IGW, NAT, Route Tables)
# [KESALAHAN DISENGAJA]: S3 Gateway VPC Endpoint TIDAK DIBUAT (A1.6 = 0)
# =========================================================================

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "TECHFEST-VPC"
  }
}

# Public Subnets
resource "aws_subnet" "public_a" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.10.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true

  tags = {
    Name = "TECHFEST-Public-Subnet-A"
  }
}

resource "aws_subnet" "public_b" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.20.20.0/24"
  availability_zone       = data.aws_availability_zones.available.names[1]
  map_public_ip_on_launch = true

  tags = {
    Name = "TECHFEST-Public-Subnet-B"
  }
}

# Private Subnets
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.110.0/24"
  availability_zone = data.aws_availability_zones.available.names[0]

  tags = {
    Name = "TECHFEST-Private-Subnet-A"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.120.0/24"
  availability_zone = data.aws_availability_zones.available.names[1]

  tags = {
    Name = "TECHFEST-Private-Subnet-B"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "igw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "TECHFEST-IGW"
  }
}

# NAT Gateway & Elastic IP
resource "aws_eip" "nat" {
  domain = "vpc"
  tags = {
    Name = "TECHFEST-NAT-EIP"
  }
}

resource "aws_nat_gateway" "nat" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public_a.id

  tags = {
    Name = "TECHFEST-NAT-Gateway"
  }

  depends_on = [aws_internet_gateway.igw]
}

# Route Tables
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }

  tags = {
    Name = "TECHFEST-Public-RT"
  }
}

resource "aws_route_table_association" "pub_a" {
  subnet_id      = aws_subnet.public_a.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "pub_b" {
  subnet_id      = aws_subnet.public_b.id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.nat.id
  }

  tags = {
    Name = "TECHFEST-Private-RT"
  }
}

resource "aws_route_table_association" "priv_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "priv_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

# =========================================================================
# 2. SECURITY GROUPS (Tiered: ALB -> APP -> RDS)
# =========================================================================

resource "aws_security_group" "alb" {
  name        = "SG-ALB"
  description = "Security Group ALB HTTP Inbound"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTP Public"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "SG-ALB"
  }
}

resource "aws_security_group" "app" {
  name        = "SG-APP"
  description = "Security Group App EC2 Chained from ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "HTTP from ALB SG only"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "SG-APP"
  }
}

resource "aws_security_group" "rds" {
  name        = "SG-RDS"
  description = "Security Group RDS MySQL from APP SG only"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "MySQL from APP SG"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "SG-RDS"
  }
}

# =========================================================================
# 3. IAM
# [KESALAHAN DISENGAJA]: Role diubah namanya menjadi CustomAppRole (D1.1 = 0)
# =========================================================================

resource "aws_iam_role" "custom_role" {
  name = "CustomAppRole"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "s3_access" {
  role       = aws_iam_role.custom_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

resource "aws_iam_instance_profile" "custom_instance_profile" {
  name = "CustomAppInstanceProfile"
  role = aws_iam_role.custom_role.name
}

# =========================================================================
# 4. S3 BUCKET & BLOCK PUBLIC ACCESS
# =========================================================================

resource "random_id" "bucket_suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "app_storage" {
  bucket        = "techfest-final-storage-${random_id.bucket_suffix.hex}"
  force_destroy = true

  tags = {
    Name = "techfest-app-bucket"
  }
}

resource "aws_s3_bucket_public_access_block" "app_storage_pab" {
  bucket = aws_s3_bucket.app_storage.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# =========================================================================
# 5. RDS MYSQL (Single-AZ Private)
# [KESALAHAN DISENGAJA]: DB Name = techfest_database_salah (bukan techfest_final_db) (C1.3 = 0)
# =========================================================================

resource "aws_db_subnet_group" "rds" {
  name       = "techfest-db-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "techfest-db-subnet-group"
  }
}

resource "aws_db_instance" "mysql" {
  identifier             = "techfest-db"
  engine                 = "mysql"
  engine_version         = "8.0"
  instance_class         = "db.t3.micro"
  allocated_storage      = 20
  db_name                = "techfest_database_salah"
  username               = "tf11_app"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.rds.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false
  skip_final_snapshot    = true

  tags = {
    Name = "techfest-final-rds"
  }
}

# =========================================================================
# 6. APPLICATION LOAD BALANCER & TARGET GROUP
# =========================================================================

resource "aws_lb" "main" {
  name               = "techfest-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = [aws_subnet.public_a.id, aws_subnet.public_b.id]

  tags = {
    Name = "techfest-alb"
  }
}

resource "aws_lb_target_group" "app_tg" {
  name        = "techfest-tg"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "instance"

  health_check {
    path                = "/up"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = {
    Name = "techfest-tg"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app_tg.arn
  }
}

# =========================================================================
# 7. LAUNCH TEMPLATE & AUTO SCALING GROUP
# [KESALAHAN DISENGAJA]:
# 1) associate_public_ip_address = true (D1.2 = 0 & Penalti P.1 = -20.0)
# 2) ASG min=2, desired=2, max=2 (E1.2 = 2.0 parsial)
# =========================================================================

resource "aws_launch_template" "app_lt" {
  name_prefix   = "techfest-lt-"
  image_id      = data.aws_ami.ubuntu.id
  instance_type = "t3.micro"

  iam_instance_profile {
    arn = aws_iam_instance_profile.custom_instance_profile.arn
  }

  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.app.id]
  }

  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    alb_dns     = aws_lb.main.dns_name
    db_host     = aws_db_instance.mysql.address
    db_password = var.db_password
    region      = var.aws_region
    s3_bucket   = aws_s3_bucket.app_storage.id
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "techfest-app-worker"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "app_asg" {
  name_prefix         = "techfest-asg-"
  vpc_zone_identifier = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  target_group_arns   = [aws_lb_target_group.app_tg.arn]

  min_size         = 2
  desired_capacity = 2
  max_size         = 2

  health_check_type         = "ELB"
  health_check_grace_period = 300

  launch_template {
    id      = aws_launch_template.app_lt.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "techfest-asg-node"
    propagate_at_launch = true
  }

  depends_on = [aws_lb_listener.http, aws_db_instance.mysql]
}

# =========================================================================
# 8. CLOUDWATCH ALARM
# =========================================================================

resource "aws_cloudwatch_metric_alarm" "high_cpu" {
  alarm_name          = "techfest-asg-high-cpu"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 120
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Alarm status jika utilisasi CPU ASG mencapai 80%"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.app_asg.name
  }
}
