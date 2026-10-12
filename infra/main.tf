# Everything the daily GitHub Actions job needs, and nothing else.
# `terraform destroy` removes all of it when the run is over.

resource "google_project_service" "apis" {
  for_each = toset([
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

resource "google_bigquery_dataset" "fx" {
  dataset_id                 = var.dataset_id
  location                   = var.bq_location
  description                = "Official National Bank of Georgia exchange rates"
  delete_contents_on_destroy = true
  labels                     = { project = "nbg-fx-pipeline" }
}

resource "google_service_account" "loader" {
  account_id   = "nbg-fx-loader"
  display_name = "NBG FX pipeline loader (GitHub Actions)"
}

# Write access to this one dataset only, plus the right to run query jobs.
resource "google_bigquery_dataset_iam_member" "loader_editor" {
  dataset_id = google_bigquery_dataset.fx.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.loader.email}"
}

resource "google_project_iam_member" "loader_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.loader.email}"
}

# Keyless auth: GitHub's OIDC token is exchanged for a short-lived token for
# the loader. No JSON key exists anywhere to leak.
resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-nbg-fx"
  display_name              = "GitHub Actions (nbg-fx)"
  depends_on                = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only workflows on main of this one repo can get a token; forks and
  # branches are rejected before any IAM check.
  attribute_condition = "assertion.repository == '${var.github_repo}' && assertion.ref == 'refs/heads/main'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonates_loader" {
  service_account_id = google_service_account.loader.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
