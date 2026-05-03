variable "project_id" {
  description = "GCP project where Stratum scanner access should be configured."
  type        = string
}

variable "region" {
  description = "Default GCP region for Stratum."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Default GCP zone for Stratum."
  type        = string
  default     = "us-central1-a"
}

variable "network" {
  description = "VPC network name used by Stratum."
  type        = string
  default     = "default"
}

variable "subnetwork" {
  description = "Optional subnetwork self-link or name used by Stratum."
  type        = string
  default     = ""
}

variable "principal" {
  description = "Optional existing IAM principal to grant, for example user:admin@example.com or serviceAccount:stratum@example.iam.gserviceaccount.com. Leave empty to create a Stratum service account."
  type        = string
  default     = ""
}

variable "service_account_id" {
  description = "Service account ID to create when principal is empty."
  type        = string
  default     = "stratum-scanner"
}
