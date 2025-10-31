#!/bin/bash
# ==============================================================================
#  GCP Resource Audit & Cost Summary (v4)
#  - Full audit, stable ordering, correct counts, cost % per active category
#  - Writes log to: /home/ganyhp/gcp-infra-terraform/gcp_audit_logs/gcp_audit_log_<PROJECT>_<TIMESTAMP>.log
# ==============================================================================

# Purpose & Functionality Summary
# Objective:
        #Automates a post-deployment audit of GCP infrastructure to identify active/inactive services and estimate relative cost impact.
#Scope:
        # Audits key GCP resource categories —
        # Compute, Network, SQL, Storage, Pub/Sub, Cloud Run, Cloud Functions, Scheduler, and Secrets.
# Key Features:
        #Runs gcloud commands for each resource type and checks if resources exist.
        #Marks each as 🟢 Active or ⚪ Inactive.
        #Estimates relative cost share (%) for active services using pre-defined weight factors.
        #Calculates total active/inactive counts for a quick health snapshot.
# Logging:
        #All results and console output are saved to
        #/home/ganyhp/gcp-infra-terraform/gcp_audit_logs/gcp_audit_log_<PROJECT>_<TIMESTAMP>.log.
#Output Summary:
        #Tabular summary of each resource’s status and cost percentage.
        #Overall totals showing number of active/inactive categories.
        #Displays an estimated cost distribution for active components.
#Purpose in Workflow:
#Designed to be executed after Terraform apply to validate and audit deployed GCP resources.
#Helps identify unused/idle components and track cost contributors.



PROJECT_ID="gany2206"
LOG_DIR="/home/ganyhp/gcp-infra-terraform/gcp_audit_logs"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
LOG_FILE="$LOG_DIR/gcp_audit_log_${PROJECT_ID}_${TIMESTAMP}.log"

mkdir -p "$LOG_DIR"

# Tee all output to log file
exec > >(tee -a "$LOG_FILE") 2>&1

echo "=============================================================================="
echo "🔍 GCP Resource Audit Summary for Project: $PROJECT_ID"
echo "📅 Timestamp: $(date -u)"
echo "📁 Log file: $LOG_FILE"
echo "=============================================================================="

# ---------------------------------------------------------------------------
# Define categories and stable display order
# ---------------------------------------------------------------------------
CATEGORIES=(Compute Network SQL Storage PubSub Run Function Scheduler Secrets)

# Relative cost weights (approximate)
declare -A COST_WEIGHTS=(
  ["Compute"]=40
  ["Network"]=6
  ["SQL"]=25
  ["Storage"]=10
  ["PubSub"]=3
  ["Run"]=8
  ["Function"]=5
  ["Scheduler"]=2
  ["Secrets"]=1
)

# Initialize status and cost usage
declare -A STATUS
declare -A COST_USAGE
for key in "${CATEGORIES[@]}"; do
  STATUS[$key]="⚪ Inactive"
  COST_USAGE[$key]=0
done

# Helper: normalized check and treat outputs that say "Listed 0 items" or empty as no resources
check_resource() {
  local key="$1"
  local label="$2"
  local cmd="$3"

  echo -e "\n▶️  Checking $label..."
  output=$(eval "$cmd" 2>/dev/null)

  if [[ -z "$output" || "$output" == *"Listed 0 items"* || "$output" == *"No resources found"* ]]; then
    echo "✅ No $label found."
    STATUS[$key]="⚪ Inactive"
    COST_USAGE[$key]=0
  else
    echo "❌ Active $label found:"
    echo "$output"
    STATUS[$key]="🟢 Active"
    COST_USAGE[$key]="${COST_WEIGHTS[$key]}"
  fi
}

# ---------------------------------------------------------------------------
# Perform checks (keep stable order and clear commands)
# ---------------------------------------------------------------------------
# Compute
check_resource "Compute" "Compute Engine Instances" "gcloud compute instances list --project=$PROJECT_ID --format='table(name,zone,status)'"

# Network (aggregate multiple checks)
net_out=$(gcloud compute networks list --project="$PROJECT_ID" --format="yaml" 2>/dev/null)
subnet_out=$(gcloud compute networks subnets list --project="$PROJECT_ID" --format="yaml" 2>/dev/null)
fw_out=$(gcloud compute firewall-rules list --project="$PROJECT_ID" --format="yaml" 2>/dev/null)
peer_out=$(gcloud compute networks peerings list --network=tf-vpc --project="$PROJECT_ID" --format="yaml" 2>/dev/null || true)

echo -e "\n▶️  Checking Network (networks / subnets / firewall / peerings)..."
if [[ -z "$net_out" && -z "$subnet_out" && -z "$fw_out" && -z "$peer_out" ]]; then
  echo "✅ No Network resources found."
  STATUS["Network"]="⚪ Inactive"
  COST_USAGE["Network"]=0
else
  echo "❌ Active Network resources found:"
  [[ -n "$net_out" ]] && echo "--- networks ---" && echo "$net_out"
  [[ -n "$subnet_out" ]] && echo "--- subnets ---" && echo "$subnet_out"
  [[ -n "$fw_out" ]] && echo "--- firewall rules ---" && echo "$fw_out"
  [[ -n "$peer_out" ]] && echo "--- peerings (tf-vpc) ---" && echo "$peer_out"
  STATUS["Network"]="🟢 Active"
  COST_USAGE["Network"]="${COST_WEIGHTS["Network"]}"
fi

# SQL
check_resource "SQL" "Cloud SQL Instances" "gcloud sql instances list --project=$PROJECT_ID --format='table(name,region,databaseVersion)'"

# Storage
check_resource "Storage" "Cloud Storage Buckets" "gcloud storage buckets list --project=$PROJECT_ID --format='table(name,location)'"

# Pub/Sub
check_resource "PubSub" "Pub/Sub Topics" "gcloud pubsub topics list --project=$PROJECT_ID --format='table(name)'"

# Cloud Run
check_resource "Run" "Cloud Run Services" "gcloud run services list --platform=managed --project=$PROJECT_ID --format='table(metadata.name,location)'"

# Cloud Functions
check_resource "Function" "Cloud Functions" "gcloud functions list --project=$PROJECT_ID --format='table(name,region)'"

# Cloud Scheduler
check_resource "Scheduler" "Cloud Scheduler Jobs" "gcloud scheduler jobs list --project=$PROJECT_ID --format='table(name,description)'"

# Secret Manager
check_resource "Secrets" "Secret Manager Secrets" "gcloud secrets list --project=$PROJECT_ID --format='table(name)'"

# ---------------------------------------------------------------------------
# Calculate total cost weight only for active categories
# ---------------------------------------------------------------------------
total_weight=0
for key in "${CATEGORIES[@]}"; do
  val=${COST_USAGE[$key]:-0}
  total_weight=$(( total_weight + val ))
done

# ---------------------------------------------------------------------------
# Display summary table
# ---------------------------------------------------------------------------
echo -e "\n=============================================================================="
echo "📋 RESOURCE STATUS SUMMARY"
echo "=============================================================================="
printf "%-15s %-12s %8s\n" "Resource Type" "Status" "Cost %"
echo "-------------------------------------------------------"

for key in "${CATEGORIES[@]}"; do
  weight=${COST_USAGE[$key]:-0}
  if (( total_weight > 0 && weight > 0 )); then
    pct=$(( weight * 100 / total_weight ))
  else
    pct=0
  fi
  printf "%-15s %-12s %6s%%\n" "$key" "${STATUS[$key]}" "$pct"
done

echo "-------------------------------------------------------"

# ---------------------------------------------------------------------------
# Totals & Cost Distribution
# ---------------------------------------------------------------------------
active_count=0
inactive_count=0
for key in "${CATEGORIES[@]}"; do
  if [[ "${STATUS[$key]}" == "🟢 Active" ]]; then
    ((active_count++))
  else
    ((inactive_count++))
  fi
done

echo -e "\n=============================================================================="
echo "📊 SUMMARY TOTALS"
echo "=============================================================================="
echo "🔹 Active Services   : $active_count"
echo "🔹 Inactive Services : $inactive_count"
echo "🔹 Total Categories  : ${#CATEGORIES[@]}"

if (( total_weight > 0 )); then
  echo -e "\n💰 Estimated Cost Distribution (only active categories):"
  for key in "${CATEGORIES[@]}"; do
    weight=${COST_USAGE[$key]:-0}
    if (( weight > 0 )); then
      pct=$(( weight * 100 / total_weight ))
      echo "   - $key → ${pct}%"
    fi
  done
else
  echo -e "\n✅ No active resources detected — no estimated cost."
fi

echo "=============================================================================="
echo "✅ Audit completed successfully for project: $PROJECT_ID"
echo "📄 Log saved to: $LOG_FILE"
echo "=============================================================================="
