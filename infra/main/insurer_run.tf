# The monthly insurer run: ingest/insurers/run.py in a container on ECS Fargate, started by
# an EventBridge Scheduler schedule. It streams every in-network file in Cigna's table of
# contents, keeps Arizona hospitals' rates, and writes JSON Lines and Parquet to the data
# bucket. Per-file status goes to a small DynamoDB table so a rerun resumes.
#
# Costs nothing between runs except image storage in ECR (cents). A run is billed per
# second of the task's vCPU and memory; see docs/04-insurer.md for measured runs.

locals {
  insurer_name   = "${var.project}-insurer"
  insurer_vcpu   = 4
  insurer_mem_gb = 8
}

# --- Image -------------------------------------------------------------------------------

resource "aws_ecr_repository" "insurer" {
  name                 = local.insurer_name
  image_tag_mutability = "MUTABLE" # scripts/push_image.py moves `latest` to each new build
  force_delete         = true      # `terraform destroy` removes the images too

  image_scanning_configuration {
    scan_on_push = true # basic scanning: free
  }
}

# Keep the last three images; older ones only cost storage.
resource "aws_ecr_lifecycle_policy" "insurer" {
  repository = aws_ecr_repository.insurer.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 3 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
      action       = { type = "expire" }
    }]
  })
}

# --- Run status --------------------------------------------------------------------------

#   PK RUN#<insurer>#<month>   SK FILE#<file name>   queued | done (stats) | failed (error)
#   PK RUN#<insurer>#<month>   SK SUMMARY            files, hours, estimated cost
resource "aws_dynamodb_table" "runs" {
  name         = "${var.project}-runs"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }
  attribute {
    name = "SK"
    type = "S"
  }
}

# --- Task --------------------------------------------------------------------------------

resource "aws_ecs_cluster" "main" {
  name = var.project # a cluster is free; Fargate bills only the running task
}

resource "aws_cloudwatch_log_group" "insurer" {
  name              = "/ecs/${local.insurer_name}"
  retention_in_days = 14
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Used by ECS itself to start the task: pull the image and send logs.
resource "aws_iam_role" "insurer_execution" {
  name               = "${local.insurer_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "insurer_execution" {
  name = "pull-image-and-log"
  role = aws_iam_role.insurer_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin" # account-wide by design; grants no image access by itself
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid      = "PullImage"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.insurer.arn
      },
      {
        Sid      = "WriteLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.insurer.arn}:*"
      },
    ]
  })
}

# Used by the code in the container: write its outputs and its status, nothing else.
resource "aws_iam_role" "insurer_task" {
  name               = "${local.insurer_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "insurer_task" {
  name = "write-insurer-data"
  role = aws_iam_role.insurer_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "WriteInsurerFiles"
        Effect = "Allow"
        Action = "s3:PutObject"
        Resource = [
          "${aws_s3_bucket.data.arn}/raw/insurer=*",
          "${aws_s3_bucket.data.arn}/parquet/insurer=*",
        ]
      },
      {
        Sid      = "RunStatus"
        Effect   = "Allow"
        Action   = ["dynamodb:Query", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.runs.arn
      },
    ]
  })
}

resource "aws_ecs_task_definition" "insurer" {
  family                   = local.insurer_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.insurer_vcpu * 1024
  memory                   = local.insurer_mem_gb * 1024
  execution_role_arn       = aws_iam_role.insurer_execution.arn
  task_role_arn            = aws_iam_role.insurer_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64" # Graviton: about 20% cheaper than x86 per vCPU-hour
  }

  container_definitions = jsonencode([{
    name      = "insurer"
    image     = "${aws_ecr_repository.insurer.repository_url}:latest"
    essential = true
    # A cap on a stuck run, which would otherwise bill until stopped. A full run is
    # expected to take 1-2 hours.
    entryPoint = ["timeout", "--signal=TERM", "4h", "python", "-m", "ingest.insurers.run"]
    command    = ["--workers", tostring(local.insurer_vcpu)]
    environment = [
      { name = "DATA_BUCKET", value = aws_s3_bucket.data.bucket },
      { name = "RUNS_TABLE", value = aws_dynamodb_table.runs.name },
      { name = "AWS_DEFAULT_REGION", value = var.region },
      { name = "TASK_VCPU", value = tostring(local.insurer_vcpu) },
      { name = "TASK_MEMORY_GB", value = tostring(local.insurer_mem_gb) },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.insurer.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "run"
      }
    }
  }])
}

# --- Network -----------------------------------------------------------------------------
# The default VPC's public subnets with a public IP: the task only makes outbound HTTPS
# calls, and this avoids a NAT gateway (about $32 a month).

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "insurer" {
  name        = local.insurer_name
  description = "Outbound only, for the insurer run"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_egress_rule" "insurer_https" {
  security_group_id = aws_security_group.insurer.id
  description       = "HTTPS: insurer files, ECR, S3, DynamoDB, CloudWatch"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "insurer_dns" {
  security_group_id = aws_security_group.insurer.id
  description       = "DNS to the VPC resolver"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = "${cidrhost(data.aws_vpc.default.cidr_block, 2)}/32"
}

# --- Schedule ----------------------------------------------------------------------------

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "insurer_scheduler" {
  name               = "${local.insurer_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "insurer_scheduler" {
  name = "run-insurer-task"
  role = aws_iam_role.insurer_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "RunTask"
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "${aws_ecs_task_definition.insurer.arn_without_revision}:*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Sid      = "PassTaskRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.insurer_execution.arn, aws_iam_role.insurer_task.arn]
      },
    ]
  })
}

# Insurers post new files on the 1st; run on the 5th at 06:00 UTC (11 pm in Arizona on
# the 4th), leaving a few days for late postings.
resource "aws_scheduler_schedule" "insurer" {
  name                = "${local.insurer_name}-monthly"
  schedule_expression = "cron(0 6 5 * ? *)"
  state               = var.insurer_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.insurer_scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.insurer.arn
      launch_type         = "FARGATE"
      task_count          = 1

      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.insurer.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 2 # retries a failed start, not a failed run
    }
  }
}

output "insurer_image_repository" {
  value = aws_ecr_repository.insurer.repository_url
}

output "insurer_run_command" {
  description = "Starts a run now (the same task the schedule starts)."
  value = join(" ", [
    "aws ecs run-task --cluster", aws_ecs_cluster.main.name,
    "--task-definition", aws_ecs_task_definition.insurer.family,
    "--launch-type FARGATE --network-configuration",
    "'awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.insurer.id}],assignPublicIp=ENABLED}'",
  ])
}

output "runs_table" {
  value = aws_dynamodb_table.runs.name
}
