output "role_arn" {
  description = "ARN of the IAM role that can read the secrets. Assume this role to fetch them."
  value       = aws_iam_role.secrets_reader.arn
}

output "kms_key_arn" {
  description = "ARN of the customer-managed KMS key encrypting the secrets."
  value       = aws_kms_key.secrets.arn
}

output "secret_arns" {
  description = "Map of secret name => ARN for every managed secret."
  value       = { for k, s in aws_secretsmanager_secret.this : s.name => s.arn }
}
