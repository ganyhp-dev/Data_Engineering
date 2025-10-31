# Project configuration
project_id = "gany2206"
region     = "asia-south1"
zone       = "asia-south1-a"
location   = "asia-south1"

# Backend bucket
tf_state_bucket = "tf-remote-state-gany2206"

# Resource labels
environment = "test"
owner       = "terraform"

# Instance configs
vm_machine_type = "e2-micro"
sql_tier        = "db-f1-micro"
