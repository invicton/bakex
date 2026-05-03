terraform {
  required_version = ">= 1.5.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  create_service_account = var.principal == ""
  role_id                = "stratumBuilder"
  member                 = local.create_service_account ? "serviceAccount:${google_service_account.stratum[0].email}" : var.principal
}

resource "google_project_service" "required" {
  for_each = toset([
    "compute.googleapis.com",
    "iap.googleapis.com"
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

resource "google_service_account" "stratum" {
  count        = local.create_service_account ? 1 : 0
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Stratum builder service account"
}

resource "google_project_iam_custom_role" "builder" {
  project     = var.project_id
  role_id     = local.role_id
  title       = "Stratum Builder"
  description = "Least-privilege role for Stratum GCP private build VMs, IAP hardening, and custom image capture."
  permissions = [
    "compute.disks.create",
    "compute.disks.delete",
    "compute.disks.get",
    "compute.firewalls.get",
    "compute.firewalls.list",
    "compute.globalOperations.get",
    "compute.images.create",
    "compute.images.delete",
    "compute.images.get",
    "compute.images.getFromFamily",
    "compute.images.list",
    "compute.instances.create",
    "compute.instances.delete",
    "compute.instances.get",
    "compute.instances.list",
    "compute.instances.setLabels",
    "compute.instances.setMetadata",
    "compute.instances.setServiceAccount",
    "compute.instances.setTags",
    "compute.instances.stop",
    "compute.instances.use",
    "compute.machineTypes.get",
    "compute.networks.get",
    "compute.networks.list",
    "compute.projects.get",
    "compute.regions.list",
    "compute.subnetworks.get",
    "compute.subnetworks.list",
    "compute.subnetworks.use",
    "compute.zoneOperations.get",
    "compute.zones.list"
  ]
}

resource "google_project_iam_member" "builder" {
  project = var.project_id
  role    = google_project_iam_custom_role.builder.name
  member  = local.member
}

resource "google_project_iam_member" "iap_tunnel" {
  project = var.project_id
  role    = "roles/iap.tunnelResourceAccessor"
  member  = local.member
}

resource "google_service_account_iam_member" "service_account_user" {
  count              = local.create_service_account ? 1 : 0
  service_account_id = google_service_account.stratum[0].name
  role               = "roles/iam.serviceAccountUser"
  member             = local.member
}

resource "google_compute_firewall" "iap_ssh" {
  project = var.project_id
  name    = "stratum-allow-iap-ssh"
  network = var.network

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["stratum-build", "stratum-scan"]

  depends_on = [google_project_service.required]
}
