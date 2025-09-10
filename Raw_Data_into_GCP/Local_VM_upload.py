import os
import json
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
import paramiko

# ---------------- CONFIG ----------------
LOCAL_FOLDER = r"C:\Users\OrCon\Documents\Learnings\Training\Exercise\GCP_project\Files"
VM_HOST = "34.142.152.147"
VM_USER = "ganesh"
VM_KEY_PATH = r"C:\Users\OrCon\Documents\Learnings\Training\Exercise\GCP_project\.ssh\ganesh_gcp_key"
DESTINATION_FOLDER = "/home/ganesh/gcpdata"
MAX_WORKERS = 2   # increase to 4–8 once stable
TRACK_ROWS = True
UPLOAD_STATE_FILE = "uploaded_files.json"  # Keeps track of uploaded files
# ---------------------------------------

# Load previously uploaded files metadata
if os.path.exists(UPLOAD_STATE_FILE):
    with open(UPLOAD_STATE_FILE, "r") as f:
        uploaded_files = json.load(f)
else:
    uploaded_files = {}

# Create SSH client
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(VM_HOST, username=VM_USER, key_filename=VM_KEY_PATH, timeout=30)

# Ensure destination folder exists on VM
stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {DESTINATION_FOLDER}")
exit_status = stdout.channel.recv_exit_status()
if exit_status != 0:
    print(f"Warning: Could not create destination folder {DESTINATION_FOLDER}")

upload_status = []

# Convert non-CSV files to CSV
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
        print(f"Conversion failed for {file_path}: {e}")
        return None

# Check if file needs upload
def needs_upload(file_path):
    stat = os.stat(file_path)
    key = os.path.abspath(file_path)
    last_modified = stat.st_mtime
    size = stat.st_size
    if key in uploaded_files:
        if uploaded_files[key]["mtime"] == last_modified and uploaded_files[key]["size"] == size:
            return False
    return True

# Upload a single file using SFTP
def upload_file(file_path):
    try:
        if not needs_upload(file_path):
            return (os.path.basename(file_path), "SKIPPED", None, None)

        file_to_upload = convert_to_csv(file_path)
        if not file_to_upload:
            return (os.path.basename(file_path), "FAILED_CONVERT", None, None)

        sftp = ssh.open_sftp()
        remote_path = f"{DESTINATION_FOLDER}/{os.path.basename(file_to_upload)}"  # FIXED path
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

print(f"Total files found: {len(all_files)}")

# Upload files in parallel
with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = [executor.submit(upload_file, f) for f in all_files]
    for future in as_completed(futures):
        upload_status.append(future.result())

# Save upload state
with open(UPLOAD_STATE_FILE, "w") as f:
    json.dump(uploaded_files, f, indent=4)

# Report
success = [s for s in upload_status if s[1] == "SUCCESS"]
skipped = [s for s in upload_status if s[1] == "SKIPPED"]
failed = [s for s in upload_status if s[1].startswith("FAILED")]
total_rows = sum(s[2] for s in success if s[2] is not None)

print(f"Uploaded successfully: {len(success)}")
print(f"Skipped (already uploaded): {len(skipped)}")
print(f"Failed uploads: {len(failed)}")
print(f"Total rows loaded: {total_rows}\n")

print("Detailed status (filename, status, rows, remote_path):")
for s in upload_status:
    print(s)

ssh.close()
