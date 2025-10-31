#!/bin/bash
# ============================================================
# Script: destroy_gcp_infra.sh
# Purpose: Safely destroy all Terraform-managed and residual GCP resources
# Author: Ganesh Automation
# ============================================================

set -euo pipefail

PROJECT_ID="gany2206"
LOG_DIR="/home/ganyhp/gcp-infra-terraform/gcp-infra-terraform/logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/destroy_log_$TIMESTAMP.log"
SUMMARY_FILE="$LOG_DIR/destroy_summary_$TIMESTAMP.txt"

mkdir -p "$LOG_DIR"

echo "============================================================" | tee -a "$LOG_FILE"
echo "Starting GCP Infrastructure Destroy Process - $TIMESTAMP" | tee -a "$LOG_FILE"
echo "Project: $PROJECT_ID" | tee -a "$LOG_FILE"
echo "============================================================" | tee -a "$LOG_FILE"

# ---------------------------------------------------------------------
# Helper: Count total resources before destroy
# ---------------------------------------------------------------------
echo "[INFO] Collecting active resource inventory..." | tee -a "$LOG_FILE"
BEFORE_RESOURCES=$(gcloud asset list --project="$PROJECT_ID" --format="value(name)" | wc -l)
echo "Total active resources before destroy: $BEFORE_RESOURCES" | tee -a "$LOG_FILE"

# ---------------------------------------------------------------------
# Step 1: Destroy dependent resources first (Cloud SQL, Memorystore, etc.)
# ---------------------------------------------------------------------
echo "[STEP 1] Destroying dependent services (Cloud SQL, Memorystore, Data Fusion, etc.)..." | tee -a "$LOG_FILE"

terraform destroy -target=google_sql_database_instance.tf-sql-instance -auto-approve >> "$LOG_FILE" 2>&1 || echo "[WARN] Cloud SQL instance not found or already deleted." | tee -a "$LOG_FILE"
terraform destroy -target=google_sql_user.tf-sql-user -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_sql_database.tf-db -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_redis_instance.tf-redis -auto-approve >> "$LOG_FILE" 2>&1 || echo "[WARN] Memorystore not found." | tee -a "$LOG_FILE"
terraform destroy -target=google_data_fusion_instance.tf-datafusion -auto-approve >> "$LOG_FILE" 2>&1 || true

# ---------------------------------------------------------------------
# Step 2: Destroy compute and container resources
# ---------------------------------------------------------------------
echo "[STEP 2] Destroying compute and container resources..." | tee -a "$LOG_FILE"

terraform destroy -target=google_compute_instance.tf-instance -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_compute_instance_group.tf-instance-group -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_container_cluster.tf-gke -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_cloud_run_service.tf-cloudrun -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_cloudfunctions_function.tf-function -auto-approve >> "$LOG_FILE" 2>&1 || true

# ---------------------------------------------------------------------
# Step 3: Destroy storage, buckets, and related services
# ---------------------------------------------------------------------
echo "[STEP 3] Destroying storage and bucket resources..." | tee -a "$LOG_FILE"

terraform destroy -target=google_storage_bucket.tf-bucket -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_storage_bucket_object.tf-object -auto-approve >> "$LOG_FILE" 2>&1 || true

# ---------------------------------------------------------------------
# Step 4: Destroy networking resources (firewalls, subnet, VPC, etc.)
# ---------------------------------------------------------------------
echo "[STEP 4] Destroying networking components..." | tee -a "$LOG_FILE"

# Destroy dependent networking items first
terraform destroy -target=google_compute_firewall.tf-firewall -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_compute_subnetwork.tf-subnet -auto-approve >> "$LOG_FILE" 2>&1 || true

# Handle Service Networking connection safely
echo "[INFO] Checking if Service Networking connection exists..." | tee -a "$LOG_FILE"
CONNECTION_ID=$(gcloud services vpc-peerings list --network=tf-vpc --project="$PROJECT_ID" --format="value(name)" || true)
if [[ -n "$CONNECTION_ID" ]]; then
  echo "[INFO] Attempting to delete private service networking connection: $CONNECTION_ID" | tee -a "$LOG_FILE"
  terraform destroy -target=google_service_networking_connection.private_vpc_connection -auto-approve >> "$LOG_FILE" 2>&1 || {
    echo "[WARN] Service Networking still in use. Retrying after checking dependencies..." | tee -a "$LOG_FILE"
    gcloud sql instances list --project="$PROJECT_ID" >> "$LOG_FILE" 2>&1
    gcloud redis instances list --project="$PROJECT_ID" >> "$LOG_FILE" 2>&1
    terraform destroy -target=google_service_networking_connection.private_vpc_connection -auto-approve >> "$LOG_FILE" 2>&1 || true
  }
fi

# Finally destroy VPC
terraform destroy -target=google_compute_network.tf-vpc -auto-approve >> "$LOG_FILE" 2>&1 || true

# ---------------------------------------------------------------------
# Step 5: Destroy IAM, secrets, schedulers, and residual items
# ---------------------------------------------------------------------
echo "[STEP 5] Cleaning up IAM, Secret Manager, Scheduler..." | tee -a "$LOG_FILE"

terraform destroy -target=google_secret_manager_secret.tf-secret -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_secret_manager_secret_version.tf-secret-version -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_cloud_scheduler_job.tf-scheduler -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_eventarc_trigger.tf-eventarc -auto-approve >> "$LOG_FILE" 2>&1 || true
terraform destroy -target=google_pubsub_topic.tf-topic -auto-approve >> "$LOG_FILE" 2>&1 || true

# ---------------------------------------------------------------------
# Step 6: Final Terraform cleanup
# ---------------------------------------------------------------------
echo "[STEP 6] Performing final Terraform cleanup..." | tee -a "$LOG_FILE"
terraform destroy -auto-approve >> "$LOG_FILE" 2>&1 || true

# ---------------------------------------------------------------------
# Step 7: Post-destroy summary
# ---------------------------------------------------------------------
echo "[STEP 7] Generating resource summary..." | tee -a "$LOG_FILE"

AFTER_RESOURCES=$(gcloud asset list --project="$PROJECT_ID" --format="value(name)" | wc -l)
DELETED_COUNT=$(( BEFORE_RESOURCES - AFTER_RESOURCES ))

echo "============================================================" | tee -a "$SUMMARY_FILE"
echo "GCP Infra Destruction Summary - $TIMESTAMP" | tee -a "$SUMMARY_FILE"
echo "============================================================" | tee -a "$SUMMARY_FILE"
echo "Project ID: $PROJECT_ID" | tee -a "$SUMMARY_FILE"
echo "Initial Resources Count : $BEFORE_RESOURCES" | tee -a "$SUMMARY_FILE"
echo "Remaining Resources     : $AFTER_RESOURCES" | tee -a "$SUMMARY_FILE"
echo "Deleted Resources Count : $DELETED_COUNT" | tee -a "$SUMMARY_FILE"
echo "" | tee -a "$SUMMARY_FILE"

if [[ "$AFTER_RESOURCES" -gt 0 ]]; then
  echo "[INFO] Listing remaining undeleted resources..." | tee -a "$SUMMARY_FILE"
  gcloud asset list --project="$PROJECT_ID" --format="value(name, assetType)" | tee -a "$SUMMARY_FILE"
  echo "" | tee -a "$SUMMARY_FILE"
  echo "Potential reasons for non-deletion:" | tee -a "$SUMMARY_FILE"
  echo "- Resource still in use by another service" | tee -a "$SUMMARY_FILE"
  echo "- IAM or permission restriction" | tee -a "$SUMMARY_FILE"
  echo "- Terraform state inconsistency" | tee -a "$SUMMARY_FILE"
else
  echo "✅ All resources successfully destroyed." | tee -a "$SUMMARY_FILE"
fi

echo "============================================================" | tee -a "$SUMMARY_FILE"
echo "Logs saved to: $LOG_FILE" | tee -a "$SUMMARY_FILE"
echo "Summary saved to: $SUMMARY_FILE" | tee -a "$SUMMARY_FILE"
echo "============================================================" | tee -a "$SUMMARY_FILE"

exit 0
