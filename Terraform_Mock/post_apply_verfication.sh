#!/bin/bash
# ============================================================
# GCP Infrastructure Post-Terraform Verification Script
# Author: Ganesh Automation
# Purpose: Verify Terraform deployed GCP resources and summarize status
# ============================================================
# This script acts as a post-deployment validation layer that automatically verifies all Terraform-managed GCP resources, 
# logs the status of each, captures failure reasons, 
# and produces a complete success/failure summary report for auditing and troubleshooting.

        # Objective:
                        # Automates post-Terraform verification of all key GCP infrastructure components to ensure successful deployment.
        # Scope Covered:
                        # Validates 13 categories of GCP resources:
                        # Enabled APIs
                        # VPC Network & Subnet
                        # IAM roles & Service Accounts
                        # GCS Buckets
                        # Artifact Registry
                        # Secret Manager
                        # Pub/Sub Topics
                        # Cloud Run Service
                        # EventArc Triggers
                        # Cloud Functions
                        # Dataproc Cluster
                        # Cloud SQL Instance (DB & Users)
                        # VPC Peering Connections
        # Execution Flow:
                        # Starts by initializing logging, project, and region details.
                        # Sequentially runs verification checks for each resource type.
                        # Each check logs Success, Failure, or Not Found (N/A equivalent).
                        # Captures error reasons for failed verifications (e.g., missing API, incorrect name, permission issue).
        # Smart Logging:
                        # Redirects all output (stdout + stderr) to both console and timestamped log file.
        # Log directory: /home/ganyhp/gcp-infra-terraform/gcp-infra-terraform/logs.
        # Automated Status Tracking:
                        # Uses associative arrays to maintain resource-wise status and failure reason.
                        # Ensures structured and traceable reporting.

PROJECT_ID="gany2206"
REGION="asia-south1"
ZONE="asia-south1-b"

# Timestamp + Log Setup
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_DIR="/home/ganyhp/gcp-infra-terraform/logs"
LOG_FILE="$LOG_DIR/infra_verification_$TIMESTAMP.log"

mkdir -p "$LOG_DIR"

# Redirect stdout & stderr
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo "🔍 GCP Infrastructure Verification Started"
echo "📅 Timestamp : $(date)"
echo "📁 Log File  : $LOG_FILE"
echo "============================================================"

#---------------------------------------------
# Internal tracking arrays
#---------------------------------------------
declare -A RESOURCE_STATUS
declare -A RESOURCE_REASON

#---------------------------------------------
# Helper Functions
#---------------------------------------------
section() {
  echo -e "\n============================================================"
  echo "🔸 $1"
  echo "============================================================"
}

check_resource() {
  local name="$1"
  local command="$2"
  local reason=""

  eval "$command" &>/tmp/verify_output.txt
  if [ $? -eq 0 ] && [ -s /tmp/verify_output.txt ]; then
    echo "✅ SUCCESS: $name"
    RESOURCE_STATUS["$name"]="SUCCESS"
    RESOURCE_REASON["$name"]="Verified successfully"
  else
    reason=$(cat /tmp/verify_output.txt | tail -n 3 | tr '\n' ' ')
    [ -z "$reason" ] && reason="Resource not found or API not enabled"
    echo "❌ FAILED: $name"
    echo "   Reason: $reason"
    RESOURCE_STATUS["$name"]="FAILED"
    RESOURCE_REASON["$name"]="$reason"
  fi
}

#---------------------------------------------
# 1️⃣ APIs
#---------------------------------------------
section "1️⃣ Checking Enabled APIs"
check_resource "Enabled APIs" "gcloud services list --project=$PROJECT_ID | grep -E 'compute|storage|pubsub|run|cloudfunctions|sqladmin|eventarc|dataproc|secretmanager'"

#---------------------------------------------
# 2️⃣ Network
#---------------------------------------------
section "2️⃣ Checking Network Resources"
check_resource "VPC Network tf-vpc" "gcloud compute networks describe tf-vpc --project=$PROJECT_ID --format='value(name)'"
check_resource "Subnet tf-subnet" "gcloud compute networks subnets describe tf-subnet --region=$REGION --project=$PROJECT_ID --format='value(name)'"
check_resource "Firewall allow-ssh" "gcloud compute firewall-rules list --project=$PROJECT_ID | grep allow-ssh"

#---------------------------------------------
# 3️⃣ IAM & Service Account
#---------------------------------------------
section "3️⃣ Checking IAM & Service Account"
check_resource "Service Account tf-test-sa" "gcloud iam service-accounts list --project=$PROJECT_ID | grep tf-test-sa"
check_resource "IAM Role storage.objectViewer" "gcloud projects get-iam-policy $PROJECT_ID --flatten='bindings[].members' --format='table(bindings.role)' | grep storage.objectViewer"

#---------------------------------------------
# 4️⃣ GCS Bucket
#---------------------------------------------
section "4️⃣ Checking GCS Bucket"
check_resource "GCS Bucket tf-artifacts" "gcloud storage buckets list --project=$PROJECT_ID | grep tf-artifacts"

#---------------------------------------------
# 5️⃣ Artifact Registry
#---------------------------------------------
section "5️⃣ Checking Artifact Registry"
check_resource "Artifact Registry tf-test-repo" "gcloud artifacts repositories list --location=$REGION --project=$PROJECT_ID | grep tf-test-repo"

#---------------------------------------------
# 6️⃣ Secret Manager
#---------------------------------------------
section "6️⃣ Checking Secret Manager"
check_resource "Secret tf-sample-secret" "gcloud secrets list --project=$PROJECT_ID | grep tf-sample-secret"
check_resource "Secret Version tf-sample-secret" "gcloud secrets versions list tf-sample-secret --project=$PROJECT_ID --format='value(name)'"

#---------------------------------------------
# 7️⃣ Pub/Sub
#---------------------------------------------
section "7️⃣ Checking Pub/Sub"
check_resource "Pub/Sub Topic tf-topic" "gcloud pubsub topics list --project=$PROJECT_ID | grep tf-topic"

#---------------------------------------------
# 8️⃣ Cloud Run
#---------------------------------------------
section "8️⃣ Checking Cloud Run"
check_resource "Cloud Run tf-cloudrun" "gcloud run services list --region=$REGION --project=$PROJECT_ID | grep tf-cloudrun"
check_resource "Cloud Run URL" "gcloud run services describe tf-cloudrun --region=$REGION --project=$PROJECT_ID --format='value(status.url)'"

#---------------------------------------------
# 9️⃣ EventArc
#---------------------------------------------
section "9️⃣ Checking EventArc Trigger"
check_resource "EventArc Trigger tf-eventarc-trigger" "gcloud eventarc triggers list --location=$REGION --project=$PROJECT_ID | grep tf-eventarc-trigger"

#---------------------------------------------
# 🔟 Cloud Function
#---------------------------------------------
section "🔟 Checking Cloud Function"
check_resource "Cloud Function tf-function" "gcloud functions list --region=$REGION --project=$PROJECT_ID | grep tf-function"

#---------------------------------------------
# 1️⃣1️⃣ Dataproc
#---------------------------------------------
section "1️⃣1️⃣ Checking Dataproc Cluster"
check_resource "Dataproc Cluster tf-dataproc" "gcloud dataproc clusters list --region=$REGION --project=$PROJECT_ID | grep tf-dataproc"

#---------------------------------------------
# 1️⃣2️⃣ Cloud SQL
#---------------------------------------------
section "1️⃣2️⃣ Checking Cloud SQL"
check_resource "Cloud SQL Instance tf-gns-postgres" "gcloud sql instances list --project=$PROJECT_ID | grep tf-gns-postgres"
check_resource "SQL Database list" "gcloud sql databases list --instance=tf-gns-postgres --project=$PROJECT_ID"
check_resource "SQL User list" "gcloud sql users list --instance=tf-gns-postgres --project=$PROJECT_ID"

#---------------------------------------------
# 1️⃣3️⃣ VPC Peering
#---------------------------------------------
section "1️⃣3️⃣ Checking VPC Peering"
check_resource "VPC Peering tf-vpc" "gcloud compute networks peerings list --network=tf-vpc --project=$PROJECT_ID"

#---------------------------------------------
# ✅ Final Summary
#---------------------------------------------
section "✅ Final Verification Summary"

printf "%-35s | %-10s | %s\n" "RESOURCE" "STATUS" "REASON"
printf "%-35s | %-10s | %s\n" "-----------------------------------" "----------" "-----------------------------------------------"

for resource in "${!RESOURCE_STATUS[@]}"; do
  printf "%-35s | %-10s | %s\n" "$resource" "${RESOURCE_STATUS[$resource]}" "${RESOURCE_REASON[$resource]}"
done | sort

echo "============================================================"
echo "Summary written to: $LOG_FILE"
echo "============================================================"
