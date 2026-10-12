variable "project_id" {
  type = string
}

variable "region" {
  type    = string
  default = "europe-west3"
}

variable "bq_location" {
  type    = string
  default = "EU"
}

variable "dataset_id" {
  type    = string
  default = "nbg_fx"
}

variable "github_repo" {
  description = "owner/name of the only repository allowed to impersonate the loader"
  type        = string
  default     = "davittchelidze1/nbg-fx-pipeline"
}
