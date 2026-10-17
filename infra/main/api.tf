# The price lookup API: api/handler.py on Lambda, behind an API Gateway HTTP API.

data "archive_file" "api" {
  type        = "zip"
  source_file = "${path.module}/../../api/handler.py" # boto3 is in the runtime already
  output_path = "${path.module}/.terraform/api.zip"
}

resource "aws_iam_role" "api" {
  name = "${var.project}-api"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Read-only, and only what the three endpoints use.
resource "aws_iam_role_policy" "api" {
  name = "read-prices"
  role = aws_iam_role.api.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ReadPrices" # GetItem: one hospital; Query by_service: compare; BatchGetItem: profiles
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:BatchGetItem"]
        Resource = [aws_dynamodb_table.prices.arn, "${aws_dynamodb_table.prices.arn}/index/by_service"]
      },
      {
        Sid      = "ReadServiceList" # search loads serving/services.json once per cold start
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.data.arn}/serving/services.json"
      },
      {
        Sid      = "WriteLogs" # its own log group only
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.api.arn}:*"
      },
    ]
  })
}

# Declared so it has a retention period and `terraform destroy` removes it (Lambda would
# otherwise create one that keeps logs forever).
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.project}-api"
  retention_in_days = 14
}

resource "aws_lambda_function" "api" {
  function_name    = "${var.project}-api"
  role             = aws_iam_role.api.arn
  runtime          = "python3.13"
  architectures    = ["arm64"] # Graviton: about 20% cheaper per millisecond than x86
  handler          = "handler.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  memory_size      = 1024 # CPU scales with memory; decoding ~400 KB of items took 1.3 s at 256
  timeout          = 10

  environment {
    variables = {
      PRICES_TABLE = aws_dynamodb_table.prices.name
      DATA_BUCKET  = aws_s3_bucket.data.bucket
      SERVICES_KEY = "serving/services.json"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api, aws_iam_role_policy.api]
}

resource "aws_apigatewayv2_api" "api" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"] # public, read-only data; the site will be on another origin
    allow_methods = ["GET"]
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# Three routes, not a catch-all: anything else is a 404 from API Gateway without
# invoking (or billing) the Lambda.
resource "aws_apigatewayv2_route" "api" {
  for_each = toset([
    "GET /services",
    "GET /services/{id}/prices",
    "GET /providers/{ccn}",
  ])
  api_id    = aws_apigatewayv2_api.api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  # Caps on what a runaway client can cost: 10 requests a second, bursts of 20.
  default_route_settings {
    throttling_rate_limit  = 10
    throttling_burst_limit = 20
  }
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

output "api_url" {
  description = "Base URL of the price lookup API."
  value       = aws_apigatewayv2_stage.api.invoke_url
}
