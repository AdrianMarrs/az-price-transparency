# Cost alarms for the whole account (the project is its only workload). An email when
# actual spend passes the limit, and one when the month is forecast to. The first two
# budgets in an account are free.

resource "aws_budgets_budget" "monthly" {
  for_each = toset(["20", "50"])

  name         = "${var.project}-monthly-${each.key}"
  budget_type  = "COST"
  limit_amount = each.key
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = ["ACTUAL", "FORECASTED"]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 100
      threshold_type             = "PERCENTAGE"
      notification_type          = notification.value
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
