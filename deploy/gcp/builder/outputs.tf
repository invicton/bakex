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
  description = "Paste this into Stratum as Service Account Email when Stratum attaches this service account to build VMs."
  value       = length(google_service_account.stratum) > 0 ? google_service_account.stratum[0].email : ""
}

output "iam_member" {
  description = "IAM member granted Stratum builder permissions."
  value       = local.member
}
