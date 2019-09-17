# This script generates the kops cluster definition file
# For 5 masters, you'll need to create the cluster in us-east-1 as each master currently
# requires its own availability zone.
# Additionally, I encountered some problems in us-east-1e and had to use 1f instead)

# Define variables
export AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id)
export AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key)
BUCKET=<YOUR_BUCKET_STORE_NAME>
export KOPS_CLUSTER_NAME=<YOUR_CLUSTER_NAME>  # should be a valid DNS name, e.g. <YOUR_CUSTER_NAME>
export KOPS_STATE_STORE=s3://${BUCKET}

# Create bucket for cluster state
aws s3api create-bucket \
    --bucket ${BUCKET} \
    --region us-east-1

# Version the bucket
aws s3api put-bucket-versioning --bucket ${BUCKET}  --versioning-configuration Status=Enabled
    
kops create cluster \
    --ssh-public-key ~/.ssh/agentscale_id_rsa.pub \
    --master-count 5 \
    --node-count 10 \
    --zones us-east-1a,us-east-1b,us-east-1c,us-east-1d,us-east-1f \
    --master-zones us-east-1a,us-east-1b,us-east-1c,us-east-1d,us-east-1f \
    --node-size t3.small \
    --master-size i3.4xlarge \
    --topology private \
    --networking kopeio-vxlan \
    --bastion \
    --name ${KOPS_CLUSTER_NAME} \
    --dry-run -oyaml > fivezones.yaml

