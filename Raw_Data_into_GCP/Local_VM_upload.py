
#####Summary 
#The script takes files from a local folder → converts them to CSV if 
#needed → uploads them to a GCP VM folder over SSH/SFTP → tracks which 
#files were uploaded so unchanged files are skipped next time → prints a detailed summary.

import os
import json
import time
import logging
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import paramiko
import requests

# ---------------- CONFIG ----------------
LOCAL_FOLDER = r"C:\Users\OrCon\Documents\Learnings\Training\Exercise\GCP_project\Files"
VM_INTERNAL_IP = "10.148.0.2"       # Internal IP from your VM details
VM_EXTERNAL_IP = "35.240.140.152"   # External IP from your VM details
VM_USER = "ganesh"
VM_KEY_PATH = r"C:\Users\OrCon\Documents\Learnings\Training\Exercise\GCP_project\.ssh\ganesh_gcp_key"
DESTINATION_FOLDER = "/home/ganesh/gcpdata"
MAX_WORKERS = 2   # increase to 4–8 once stable
TRACK_ROWS = True
UPLOAD_STATE_FILE = "uploaded_files.json"  # Keeps track of uploaded files
LOG_FILE = "upload.log"
# ---------------------------------------

# ---------------- Logging Setup ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler()  # also prints to console
    ]
)
logger = logging.getLogger()

# ---------------- VM Host Detection ----------------
def get_vm_host():
    """Detect whether to use internal or external IP based on environment."""
    try:
        r = requests.get(
            "http://metadata.google.internal/computeMetadata/v1/instance/id",
            headers={"Metadata-Flavor": "Google"},
            timeout=2
        )
        if r.status_code == 200:
            logger.info("Running inside GCP → using Internal IP")
            return VM_INTERNAL_IP
    except Exception:
        logger.info("Running outside GCP → using External IP")
    return VM_EXTERNAL_IP

VM_HOST = get_vm_host()

# ---------------- SSH Connection with Retry ----------------
def create_ssh_client(host, user, key_path, retries=3):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    for attempt in range(1, retries + 1):
        try:
            ssh.connect(host, username=user, key_filename=key_path, timeout=30)
            logger.info(f"✅ Connected to {host}")
            return ssh
        except Exception as e:
            wait_time = 2 ** attempt
            logger.warning(f"❌ SSH attempt {attempt} failed: {e}. Retrying in {wait_time}s...")
            time.sleep(wait_time)

    raise Exception(f"Failed to connect to {host} after {retries} attempts")

ssh = create_ssh_client(VM_HOST, VM_USER, VM_KEY_PATH)

# Ensure destination folder exists on VM
stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {DESTINATION_FOLDER}")
exit_status = stdout.channel.recv_exit_status()
if exit_status != 0:
    logger.warning(f"Could not create destination folder {DESTINATION_FOLDER}")

# ---------------- File Upload Logic ----------------
upload_status = []

# Load previously uploaded files metadata
if os.path.exists(UPLOAD_STATE_FILE):
    with open(UPLOAD_STATE_FILE, "r") as f:
        uploaded_files = json.load(f)
else:
    uploaded_files = {}

def convert_to_csv(file_path):
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".csv":
        return file_path
    try:
        if ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file_path)
        elif ext == ".json":
            df = pd.read_json(file_path)
        elif ext == ".parquet":
            df = pd.read_parquet(file_path)
        elif ext == ".tsv":
            df = pd.read_csv(file_path, sep="\t")
        else:
            return None
        csv_file = os.path.splitext(file_path)[0] + ".csv"
        df.to_csv(csv_file, index=False)
        return csv_file
    except Exception as e:
        logger.error(f"Conversion failed for {file_path}: {e}")
        return None

def needs_upload(file_path):
    stat = os.stat(file_path)
    key = os.path.abspath(file_path)
    last_modified = stat.st_mtime
    size = stat.st_size
    if key in uploaded_files:
        if uploaded_files[key]["mtime"] == last_modified and uploaded_files[key]["size"] == size:
            return False
    return True

def upload_file(file_path):
    try:
        if not needs_upload(file_path):
            return (os.path.basename(file_path), "SKIPPED", None, None)

        file_to_upload = convert_to_csv(file_path)
        if not file_to_upload:
            return (os.path.basename(file_path), "FAILED_CONVERT", None, None)

        sftp = ssh.open_sftp()
        remote_path = f"{DESTINATION_FOLDER}/{os.path.basename(file_to_upload)}"
        sftp.put(file_to_upload, remote_path)
        sftp.close()

        rows = None
        if TRACK_ROWS and file_to_upload.endswith(".csv"):
            try:
                rows = sum(1 for _ in open(file_to_upload, encoding="utf-8")) - 1
            except Exception:
                rows = None

        stat = os.stat(file_path)
        uploaded_files[os.path.abspath(file_path)] = {"mtime": stat.st_mtime, "size": stat.st_size}

        return (os.path.basename(file_to_upload), "SUCCESS", rows, remote_path)
    except Exception as e:
        return (os.path.basename(file_path), f"FAILED_UPLOAD: {e}", None, None)

# Gather all files recursively
all_files = []
for root, _, files in os.walk(LOCAL_FOLDER):
    for file in files:
        all_files.append(os.path.join(root, file))

logger.info(f"Total files found: {len(all_files)}")

# Upload files in parallel
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = [executor.submit(upload_file, f) for f in all_files]
    for future in as_completed(futures):
        upload_status.append(future.result())

# Save upload state
with open(UPLOAD_STATE_FILE, "w") as f:
    json.dump(uploaded_files, f, indent=4)

# ---------------- Report ----------------
success = [s for s in upload_status if s[1] == "SUCCESS"]
skipped = [s for s in upload_status if s[1] == "SKIPPED"]
failed = [s for s in upload_status if s[1].startswith("FAILED")]
total_rows = sum(s[2] for s in success if s[2] is not None)

logger.info(f"Uploaded successfully: {len(success)}")
logger.info(f"Skipped (already uploaded): {len(skipped)}")
logger.info(f"Failed uploads: {len(failed)}")
logger.info(f"Total rows loaded: {total_rows}\n")

logger.info("Detailed status (filename, status, rows, remote_path):")
for s in upload_status:
    logger.info(s)

ssh.close()




#####################Detailed summary #########
# 🔹 Configuration & Setup
# Defines configuration values:
# Local folder (LOCAL_FOLDER) containing files to upload.
# VM host IP (VM_HOST), SSH username (VM_USER), SSH private key (VM_KEY_PATH).
# Destination folder on the VM (DESTINATION_FOLDER).
# Max parallel uploads (MAX_WORKERS).
# Whether to count rows in CSV (TRACK_ROWS).
# JSON file to track upload state (UPLOAD_STATE_FILE).
# Loads upload state:
# Reads uploaded_files.json if it exists → keeps track of which files were already uploaded (using file size and last modified time).

# 🔹 SSH Connection
# Creates an SSH client using Paramiko and connects to the VM.
# Ensures destination folder exists on the VM by running mkdir -p <DESTINATION_FOLDER>.

# 🔹 File Handling
# Defines convert_to_csv(file_path):
# If the file is already CSV → returns as is.
# If Excel (.xls / .xlsx) → converts to CSV.
# If JSON → converts to CSV.
# If Parquet → converts to CSV.
# If TSV → converts to CSV.
# Other formats → ignored.
# Defines needs_upload(file_path):
# Checks if file has changed (mtime or size).
# If unchanged since last upload → skips upload.

# 🔹 Upload Process
# Defines upload_file(file_path):
# Skips upload if file unchanged.
# Converts file to CSV if needed.
# Uses SFTP (ssh.open_sftp()) to upload the file to the VM destination folder.
# If CSV → optionally counts number of rows.
# Updates uploaded_files dictionary with file’s last modified time and size.
# Returns status: (filename, "SUCCESS"/"FAILED"/"SKIPPED", row_count, remote_path).

# 🔹 Main Execution
# Collects all files recursively from LOCAL_FOLDER.
# Prints total number of files found.
# Uploads files in parallel using ThreadPoolExecutor with MAX_WORKERS threads.
# Stores upload results in upload_status.

# 🔹 Post-Processing
# Saves updated upload state into uploaded_files.json so next run can skip unchanged files.
# Generates summary report:
# Number of successful uploads.
# Number skipped (already uploaded & unchanged).
# Number of failed uploads.
# Total rows uploaded (for CSVs).
# Prints detailed status for each file.
# Closes SSH connection.
