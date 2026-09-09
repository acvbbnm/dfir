output "eventbridge_bus_arn" {
  value = aws_cloudwatch_event_bus.security.arn
}

output "step_functions_arn" {
  value = aws_sfn_state_machine.collection.arn
}

output "lambda_function_arns" {
  value = { for k, v in aws_lambda_function.this : k => v.arn }
}

output "cases_table_name" {
  value = aws_dynamodb_table.cases.name
}

output "dedup_table_name" {
  value = aws_dynamodb_table.dedup.name
}

output "alert_queue_table_name" {
  value = aws_dynamodb_table.alert_queue.name
}

output "collection_target_role_arn" {
  value = aws_iam_role.collection_target.arn
}

output "ssm_document_name" {
  value = aws_ssm_document.velociraptor_collect.name
}
