# Terraform Setup – Provider, Backend, Versions
###########################################################
terraform {
  required_version = ">= 1.3.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
  }

  backend "gcs" {
    bucket = "tf-remote-state-gany2206"
    prefix = "terraform/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}

locals {
  labels = {
    env   = var.environment != "" ? var.environment : "test"
    owner = var.owner != "" ? var.owner : "terraform"
  }
}

###########################################################
# Enable Required Google Cloud APIs
###########################################################
resource "google_project_service" "enabled" {
  for_each = toset([
    "compute.googleapis.com",
    "iam.googleapis.com",
    "cloudbuild.googleapis.com",
    "storage.googleapis.com",
    "pubsub.googleapis.com",
    "cloudfunctions.googleapis.com",
    "eventarc.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
    "dataproc.googleapis.com",
    "secretmanager.googleapis.com"
  ])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

###########################################################
# NETWORK: VPC, Subnet, Firewall
###########################################################
resource "google_compute_network" "vpc" {
  name                    = "tf-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  depends_on              = [google_project_service.enabled]
}

resource "google_compute_subnetwork" "subnet" {
  name                     = "tf-subnet"
  ip_cidr_range            = "10.0.0.0/20"
  region                   = var.region
  network                  = google_compute_network.vpc.self_link
  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_ssh" {
  name    = "allow-ssh"
  network = google_compute_network.vpc.name

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }

  source_ranges = ["0.0.0.0/0"]
  direction     = "INGRESS"
  target_tags   = ["ssh"]
  description   = "Allow SSH (testing only)"
}

###########################################################
# IAM: Service Account + Minimal Role
###########################################################
resource "google_service_account" "tf_sa" {
  account_id   = "tf-test-sa"
  display_name = "Terraform Test SA"
}

resource "google_project_iam_member" "sa_storage" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.tf_sa.email}"
}

###########################################################
# GCS Bucket (Artifacts)
###########################################################
resource "random_id" "suffix" {
  byte_length = 4
}

resource "google_storage_bucket" "artifacts" {
  name                        = "tf-artifacts-${random_id.suffix.hex}"
  location                    = var.location
  force_destroy               = true
  uniform_bucket_level_access = true

  labels = local.labels

  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 30 }
  }
}

###########################################################
# Artifact Registry (Docker)
###########################################################
resource "google_artifact_registry_repository" "repo" {
  location       = var.region
  repository_id  = "tf-test-repo"
  format         = "DOCKER"
  description    = "Test Repo"
  labels         = local.labels
}

###########################################################
# Secret Manager Secret
###########################################################
resource "google_secret_manager_secret" "secret" {
  secret_id = "tf-sample-secret"

  replication {
    auto {}
  }

  labels = local.labels
}

resource "google_secret_manager_secret_version" "secret_version" {
  secret      = google_secret_manager_secret.secret.id
  secret_data = "This is a sample secret value"
}

###########################################################
# Pub/Sub Topic
###########################################################
resource "google_pubsub_topic" "topic" {
  name   = "tf-topic"
  labels = local.labels
}

###########################################################
# Cloud Run Service (minimal, public)
###########################################################
resource "google_cloud_run_service" "run" {
  name     = "tf-cloudrun"
  location = var.region

  template {
    metadata {
      annotations = {
        "autoscaling.knative.dev/maxScale" = "1"
      }
      labels = local.labels
    }

    spec {
      containers {
        image = "gcr.io/cloudrun/hello"
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }

  autogenerate_revision_name = true
}

resource "google_cloud_run_service_iam_member" "invoker" {
  service  = google_cloud_run_service.run.name
  location = google_cloud_run_service.run.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

###########################################################
# Eventarc Trigger (Pub/Sub -> Cloud Run)
###########################################################
resource "google_eventarc_trigger" "trigger" {
  name     = "tf-eventarc-trigger"
  location = var.region
  project  = var.project_id

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.pubsub.topic.v1.messagePublished"
  }

  destination {
    cloud_run_service {
      service = google_cloud_run_service.run.name
      region  = var.region
    }
  }

  transport {
    pubsub {
      topic = google_pubsub_topic.topic.id
    }
  }

  depends_on = [google_cloud_run_service.run]
}

###########################################################
# Cloud Function (Hello World)
###########################################################
resource "google_storage_bucket_object" "function_zip" {
  name   = "function.zip"
  bucket = google_storage_bucket.artifacts.name
  source = "${path.module}/function.zip"
}

resource "google_cloudfunctions_function" "function" {
  name        = "tf-function"
  runtime     = "python39"
  entry_point = "hello_world"
  region      = var.region

  source_archive_bucket = google_storage_bucket.artifacts.name
  source_archive_object = google_storage_bucket_object.function_zip.name

  trigger_http        = true
  available_memory_mb = 128

  labels = local.labels
}

###########################################################
# Dataproc (Minimal Single Node)
###########################################################
resource "google_dataproc_cluster" "cluster" {
  name   = "tf-dataproc"
  region = var.region

  cluster_config {
    master_config {
      num_instances = 1
      machine_type  = "e2-standard-2" # supported type
      disk_config {
        boot_disk_size_gb = 30
      }
    }

    worker_config {
      num_instances = 0
    }
  }

  depends_on = [google_project_service.enabled]
}

###########################################################
# VPC Peering for Private Services (Cloud SQL, etc.)
###########################################################
resource "google_compute_global_address" "private_ip_alloc" {
  name          = "tf-private-ip-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.self_link
}

resource "google_service_networking_connection" "private_vpc_connection" {
  network                 = google_compute_network.vpc.self_link
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_ip_alloc.name]
  depends_on              = [google_project_service.enabled]
}

###########################################################
# Cloud SQL (PostgreSQL) – Private IP
###########################################################
resource "google_sql_database_instance" "postgres_instance" {
  name                = "tf-gns-postgres"
  region              = var.region
  database_version    = "POSTGRES_14"
  deletion_protection = false

  settings {
    tier = "db-f1-micro"

    ip_configuration {
      ipv4_enabled    = false
      private_network = google_compute_network.vpc.self_link
    }
  }

  depends_on = [google_service_networking_connection.private_vpc_connection]
}

resource "google_sql_database" "default_db" {
  name     = "testdb"
  instance = google_sql_database_instance.postgres_instance.name
}

resource "google_sql_user" "default_user" {
  name     = "testuser"
  instance = google_sql_database_instance.postgres_instance.name
  password = "Test@1234"
}
