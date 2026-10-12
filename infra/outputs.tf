# Set these as GitHub repository variables (not secrets: none of them grant access on their own).
output "GCP_PROJECT" {
  value = var.project_id
}

output "GCP_WIF_PROVIDER" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "GCP_SERVICE_ACCOUNT" {
  value = google_service_account.loader.email
}
