# The hospital pipeline: ingest/pipeline.py in a container on ECS Fargate Spot. One task
# runs a list of states: download each hospital's price file, parse it, write its rows to
# the Parquet lake in the data bucket (lake/), then build the DuckDB warehouse inside the
# task and upload each state's site files (docs/03-cloud.md).
#
# Nothing runs until started: by hand (output pipeline_run_command) or by the weekly
# schedule below, which is created turned off (var.pipeline_schedule_enabled). Costs
# nothing between runs except image storage in ECR. Spot is billed per second at about
# 70% below on-demand, and can be stopped with two minutes' notice; a rerun skips the
# hospitals already done.

locals {
  pipeline_name    = "${var.project}-pipeline"
  pipeline_vcpu    = 4
  pipeline_mem_gb  = 30 # the most for 4 vCPU; a parse peaks near 3.5 GB at a 0.5 GB file
  pipeline_disk_gb = 100
}

resource "aws_ecr_repository" "pipeline" {
  name                 = local.pipeline_name
  image_tag_mutability = "MUTABLE" # scripts/push_image.py moves `latest` to each new build
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "pipeline" {
  repository = aws_ecr_repository.pipeline.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 3 images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 3 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_cloudwatch_log_group" "pipeline" {
  name              = "/ecs/${local.pipeline_name}"
  retention_in_days = 14
}

# Spot as well as on-demand for the cluster. The insurer run keeps its own launch type.
resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}

resource "aws_iam_role" "pipeline_execution" {
  name               = "${local.pipeline_name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "pipeline_execution" {
  name = "pull-image-and-log"
  role = aws_iam_role.pipeline_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "EcrLogin"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Sid      = "PullImage"
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.pipeline.arn
      },
      {
        Sid      = "WriteLogs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.pipeline.arn}:*"
      },
    ]
  })
}

# The code in the container: the lake and raw copies in the data bucket, the site's data
# files, and clearing them from the site's cache. Nothing else.
resource "aws_iam_role" "pipeline_task" {
  name               = "${local.pipeline_name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy" "pipeline_task" {
  name = "lake-and-site-data"
  role = aws_iam_role.pipeline_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListBuckets"
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = [aws_s3_bucket.data.arn, aws_s3_bucket.site.arn]
      },
      {
        Sid    = "LakeAndRawFiles"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = [
          "${aws_s3_bucket.data.arn}/lake/*",
          "${aws_s3_bucket.data.arn}/raw/*",
          "${aws_s3_bucket.data.arn}/parquet/*",
        ]
      },
      {
        Sid      = "SiteDataFiles"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.site.arn}/data/*"
      },
      {
        Sid      = "ClearSiteDataCache"
        Effect   = "Allow"
        Action   = "cloudfront:CreateInvalidation"
        Resource = aws_cloudfront_distribution.site.arn
      },
    ]
  })
}

resource "aws_ecs_task_definition" "pipeline" {
  family                   = local.pipeline_name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = local.pipeline_vcpu * 1024
  memory                   = local.pipeline_mem_gb * 1024
  execution_role_arn       = aws_iam_role.pipeline_execution.arn
  task_role_arn            = aws_iam_role.pipeline_task.arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64" # Fargate Spot doesn't run ARM64
  }

  ephemeral_storage {
    size_in_gib = local.pipeline_disk_gb # files in progress, and DuckDB's spill
  }

  container_definitions = jsonencode([{
    name      = "pipeline"
    image     = "${aws_ecr_repository.pipeline.repository_url}:latest"
    essential = true
    # A cap on a stuck run, which would otherwise bill until stopped.
    entryPoint = ["timeout", "--signal=TERM", "12h", "python", "-m", "ingest.pipeline"]
    # The states to run; a run started by hand passes its own (pipeline_run_command).
    command = ["--workers", tostring(local.pipeline_vcpu), "--state", "AZ"]
    environment = [
      { name = "LAKE", value = "s3://${aws_s3_bucket.data.bucket}/lake" },
      { name = "DATA_BUCKET", value = aws_s3_bucket.data.bucket },
      { name = "SITE_BUCKET", value = aws_s3_bucket.site.bucket },
      { name = "SITE_DISTRIBUTION_ID", value = aws_cloudfront_distribution.site.id },
      { name = "AWS_DEFAULT_REGION", value = var.region },
      { name = "AWS_REGION", value = var.region },
      # DuckDB's cap, leaving room for the OS; past it, the build spills to disk.
      { name = "DUCKDB_MEMORY", value = "${local.pipeline_mem_gb - 4}GB" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.pipeline.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "run"
      }
    }
  }])
}

resource "aws_security_group" "pipeline" {
  name        = local.pipeline_name
  description = "Outbound only, for the hospital pipeline"
  vpc_id      = data.aws_vpc.default.id
}

# Price files are almost all on HTTPS, but a few hospitals still serve plain HTTP.
resource "aws_vpc_security_group_egress_rule" "pipeline_https" {
  security_group_id = aws_security_group.pipeline.id
  description       = "HTTPS: price files, ECR, S3, CloudWatch"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "pipeline_http" {
  security_group_id = aws_security_group.pipeline.id
  description       = "HTTP: the few price files not on HTTPS"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_egress_rule" "pipeline_dns" {
  security_group_id = aws_security_group.pipeline.id
  description       = "DNS to the VPC resolver"
  ip_protocol       = "udp"
  from_port         = 53
  to_port           = 53
  cidr_ipv4         = "${cidrhost(data.aws_vpc.default.cidr_block, 2)}/32"
}

resource "aws_iam_role" "pipeline_scheduler" {
  name               = "${local.pipeline_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "pipeline_scheduler" {
  name = "run-pipeline-task"
  role = aws_iam_role.pipeline_scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "RunTask"
        Effect    = "Allow"
        Action    = "ecs:RunTask"
        Resource  = "${aws_ecs_task_definition.pipeline.arn_without_revision}:*"
        Condition = { ArnEquals = { "ecs:cluster" = aws_ecs_cluster.main.arn } }
      },
      {
        Sid      = "PassTaskRoles"
        Effect   = "Allow"
        Action   = "iam:PassRole"
        Resource = [aws_iam_role.pipeline_execution.arn, aws_iam_role.pipeline_task.arn]
      },
    ]
  })
}

# Weekly refresh, Mondays 06:00 UTC. Created turned off: after the initial pass the data is
# kept as it is until a refresh is chosen (October 2026).
resource "aws_scheduler_schedule" "pipeline" {
  name                = "${local.pipeline_name}-weekly"
  schedule_expression = "cron(0 6 ? * MON *)"
  state               = var.pipeline_schedule_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_ecs_cluster.main.arn
    role_arn = aws_iam_role.pipeline_scheduler.arn

    ecs_parameters {
      task_definition_arn = aws_ecs_task_definition.pipeline.arn
      task_count          = 1

      capacity_provider_strategy {
        capacity_provider = "FARGATE_SPOT"
        weight            = 1
      }

      network_configuration {
        subnets          = data.aws_subnets.default.ids
        security_groups  = [aws_security_group.pipeline.id]
        assign_public_ip = true
      }
    }

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

output "pipeline_image_repository" {
  value = aws_ecr_repository.pipeline.repository_url
}

output "pipeline_run_command" {
  description = "Starts a run on Spot now; replace the states at the end."
  value = join(" ", [
    "aws ecs run-task --cluster", aws_ecs_cluster.main.name,
    "--task-definition", aws_ecs_task_definition.pipeline.family,
    "--capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1",
    "--network-configuration",
    "'awsvpcConfiguration={subnets=[${join(",", data.aws_subnets.default.ids)}],securityGroups=[${aws_security_group.pipeline.id}],assignPublicIp=ENABLED}'",
    "--overrides '{\"containerOverrides\":[{\"name\":\"pipeline\",\"command\":[\"--workers\",\"${local.pipeline_vcpu}\",\"--state\",\"TX\"]}]}'",
  ])
}
