###########################################################
# VARIABLES – Central Configuration
###########################################################

# Project configuration
variable "project_id" {
  description = "GCP project ID where resources will be created"
  type        = string
}

variable "region" {
  description = "Default region for all resources"
  type        = string
  default     = "asia-south1"
}

variable "zone" {
  description = "Default zone for compute resources"
  type        = string
  default     = "asia-south1-a"
}

variable "location" {
  description = "Default location for regional services"
  type        = string
  default     = "asia-south1"
}

# Naming & labels
variable "environment" {
  description = "Environment tag for labeling (e.g., dev, test, prod)"
  type        = string
  default     = "test"
}

variable "owner" {
  description = "Label to identify the resource owner"
  type        = string
  default     = "terraform"
}

# Compute
variable "vm_machine_type" {
  description = "Machine type for test VM"
  type        = string
  default     = "e2-micro"
}

# Cloud SQL
variable "sql_tier" {
  description = "Tier for Cloud SQL instance (choose cost-effective type)"
  type        = string
  default     = "db-f1-micro"
}

# GCS Bucket for remote backend
variable "tf_state_bucket" {
  description = "Name of GCS bucket used for Terraform remote state"
  type        = string
}

variable "deletion_protection" {
  description = "Enable or disable deletion protection for Cloud SQL instance"
  type        = bool
  default     = true
}
