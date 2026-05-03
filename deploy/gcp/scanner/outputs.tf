output "project_id" {
  description = "Paste this into Stratum as GCP Project ID."
  value       = var.project_id
}

output "zone" {
  description = "Paste this into Stratum as Zone."
  value       = var.zone
}

output "network" {
  description = "Paste this into Stratum as VPC Network."
  value       = var.network
}

output "subnetwork" {
  description = "Paste this into Stratum as Subnetwork if set."
  value       = var.subnetwork
}

output "service_account_email" {
  description = "Service account email created by this module, or empty when using an existing principal."
  value       = length(google_service_account.stratum) > 0 ? google_service_account.stratum[0].email : ""
}

output "iam_member" {
  description = "IAM member granted Stratum scanner permissions."
  value       = local.member
}
