#!/bin/bash

# Prompt for user inputs
read -p "Enter SAP URL: " SAP_URL
read -p "Enter Agent Name [spa_multi_agent_system]: " AGENT_NAME
AGENT_NAME=${AGENT_NAME:-spa_multi_agent_system}
read -p "Enter AWS Secrets Manager Secret Name for SAP credentials [SAPDEMOCRED]: " SECRET_NAME
SECRET_NAME=${SECRET_NAME:-SAPDEMOCRED}

# Set default resource prefix
RESOURCE_PREFIX=${1:-ChatApp}

STACK_NAME="rfq-assistant-stack"
BUCKET_PREFIX="react-chat-app-bucket"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region || echo "us-east-1")

# Data buckets
SAP_DATA_BUCKET="sapdata-${ACCOUNT_ID}"
COMPLIANCE_DATA_BUCKET="compliancedata-${ACCOUNT_ID}"
KB_BUCKET="spa-table-structure-query-${ACCOUNT_ID}"
LAYER_BUCKET="chatapp-lambda-layers-${ACCOUNT_ID}"
ATHENA_BUCKET="athena-query-bucket-${ACCOUNT_ID}"

echo "=== RFQ Assistant Deployment ==="
echo "Account ID: $ACCOUNT_ID"
echo "Region: $REGION"

# Check prerequisites
if ! command -v node &> /dev/null; then
    echo "ERROR: Node.js not found. Please install Node.js 18+ from https://nodejs.org"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo "ERROR: npm not found. Please install npm (usually comes with Node.js)"
    exit 1
fi

if ! command -v zip &> /dev/null; then
    echo "ERROR: zip not found. Please install zip:"
    echo "  - macOS: brew install zip (or use built-in zip)"
    echo "  - Ubuntu/Debian: sudo apt-get install zip"
    echo "  - RHEL/CentOS: sudo yum install zip"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 not found. Please install Python 3.12+ from https://python.org"
    exit 1
fi

if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    echo "ERROR: pip not found. Please install pip for Python 3"
    exit 1
fi

echo "Installing dependencies..."
npm install

# Create data buckets
echo "Creating data buckets..."
aws s3 mb s3://$SAP_DATA_BUCKET 2>/dev/null || echo "Bucket $SAP_DATA_BUCKET already exists"
aws s3 mb s3://$COMPLIANCE_DATA_BUCKET 2>/dev/null || echo "Bucket $COMPLIANCE_DATA_BUCKET already exists"
aws s3 mb s3://$KB_BUCKET 2>/dev/null || echo "Bucket $KB_BUCKET already exists"
aws s3 mb s3://$LAYER_BUCKET 2>/dev/null || echo "Bucket $LAYER_BUCKET already exists"
aws s3 mb s3://$ATHENA_BUCKET 2>/dev/null || echo "Bucket $ATHENA_BUCKET already exists"

# Unzip and upload sample data
if [ -f "sample_data.zip" ]; then
    echo "Extracting and uploading SAP data..."
    unzip -q -o sample_data.zip -d temp_sap_data
    # If zip contains source/ folder, use it directly; otherwise use root
    if [ -d "temp_sap_data/source" ]; then
        aws s3 sync temp_sap_data/source/ s3://$SAP_DATA_BUCKET/source/ --delete
    else
        aws s3 sync temp_sap_data/ s3://$SAP_DATA_BUCKET/source/ --delete
    fi
    rm -rf temp_sap_data
    echo "[OK] SAP data uploaded to s3://$SAP_DATA_BUCKET/source/"
else
    echo "[WARNING] sample_data.zip not found, skipping SAP data upload"
fi

if [ -f "sample_comp_data.zip" ]; then
    echo "Extracting and uploading compliance data..."
    unzip -q -o sample_comp_data.zip -d temp_comp_data
    # Flatten directory structure - move files from subdirectories to root
    find temp_comp_data -type f -exec mv {} temp_comp_data/ \; 2>/dev/null
    find temp_comp_data -mindepth 1 -type d -exec rm -rf {} \; 2>/dev/null
    aws s3 sync temp_comp_data/ s3://$COMPLIANCE_DATA_BUCKET/ --delete --exclude "*/"
    rm -rf temp_comp_data
    echo "[OK] Compliance data uploaded to s3://$COMPLIANCE_DATA_BUCKET/"
else
    echo "[WARNING] sample_comp_data.zip not found, skipping compliance data upload"
fi

if [ -f "sample_kb_data.zip" ]; then
    echo "Extracting and uploading knowledge base data..."
    unzip -q -o sample_kb_data.zip -d temp_kb_data
    # If zip contains sample_kb_data/ folder, use it directly; otherwise use root
    if [ -d "temp_kb_data/sample_kb_data" ]; then
        aws s3 sync temp_kb_data/sample_kb_data/ s3://$KB_BUCKET/ --delete
    else
        aws s3 sync temp_kb_data/ s3://$KB_BUCKET/ --delete
    fi
    rm -rf temp_kb_data
    echo "[OK] Knowledge base data uploaded to s3://$KB_BUCKET/"
else
    echo "[WARNING] sample_kb_data.zip not found, skipping KB data upload"
fi

echo "Creating Lambda Layer for python-jose..."
mkdir -p lambda_layer/python
pip install python-jose cryptography -t lambda_layer/python/ --quiet
cd lambda_layer && zip -r ../python-jose-layer.zip python > /dev/null && cd ..

echo "Uploading Lambda Layer to S3..."
aws s3 cp python-jose-layer.zip s3://$LAYER_BUCKET/

echo "Creating OpenSearch Lambda Layer..."
mkdir -p opensearch_layer/python
pip install opensearch-py requests requests-aws4auth -t opensearch_layer/python/ --quiet
cd opensearch_layer && zip -r ../opensearch-layer.zip python > /dev/null && cd ..
aws s3 cp opensearch-layer.zip s3://$LAYER_BUCKET/

echo "Uploading Glue catalog export..."
if [ -f "glue_catalog_export.zip" ]; then
    GLUE_CATALOG_BUCKET="glue-catalog-${ACCOUNT_ID}"
    aws s3 mb s3://$GLUE_CATALOG_BUCKET 2>/dev/null || echo "Bucket already exists"
    aws s3 cp glue_catalog_export.zip s3://$GLUE_CATALOG_BUCKET/
    echo "[OK] Glue catalog uploaded"
fi

echo "Deploying CloudFormation stack with prefix: $RESOURCE_PREFIX"
if [ ! -f "infrastructure.yaml" ]; then
    echo "ERROR: infrastructure.yaml not found in current directory"
    exit 1
fi

aws cloudformation deploy \
  --template-file infrastructure.yaml \
  --stack-name $STACK_NAME \
  --parameter-overrides \
    ResourcePrefix=$RESOURCE_PREFIX \
    BucketName=$BUCKET_PREFIX \
    LayerBucketName=$LAYER_BUCKET \
    KnowledgeBaseBucketName=$KB_BUCKET \
    GlueCatalogBucketName=glue-catalog-${ACCOUNT_ID} \
    SAPSecretName=$SECRET_NAME \
  --capabilities CAPABILITY_IAM

if [ $? -ne 0 ]; then
    echo "ERROR: CloudFormation deployment failed"
    exit 1
fi

echo "Getting stack outputs..."
REGION=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].StackId' --output text | cut -d: -f4)
BUCKET_NAME=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`BucketName`].OutputValue' --output text)
USER_POOL_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' --output text)
USER_POOL_CLIENT_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' --output text)
CLOUDFRONT_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontURL`].OutputValue' --output text)
DISTRIBUTION_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`DistributionId`].OutputValue' --output text)
WEBSOCKET_URL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`WebSocketUrl`].OutputValue' --output text)
echo "Detected region from stack: $REGION"

echo "Updating AWS config..."
mkdir -p src
cat > src/aws-config.js << EOF
export const awsConfig = {
  Auth: {
    Cognito: {
      userPoolId: '$USER_POOL_ID',
      userPoolClientId: '$USER_POOL_CLIENT_ID',
      region: '$REGION'
    }
  },
  API: {
    REST: {
      chatApi: {
        endpoint: '$WEBSOCKET_URL',
        region: '$REGION'
      }
    }
  }
};
EOF

echo "Building React app..."
npm run build

if [ -d "build" ]; then
    echo "Deploying to S3..."
    aws s3 sync build/ s3://$BUCKET_NAME --delete
    
    echo "Invalidating CloudFront cache..."
    if [ ! -z "$DISTRIBUTION_ID" ]; then
        aws cloudfront create-invalidation --distribution-id $DISTRIBUTION_ID --paths "/*"
    fi
else
    echo "⚠ Build directory not found, skipping S3 deployment"
fi

echo "Starting Glue crawlers..."
SAP_CRAWLER="${RESOURCE_PREFIX}-sap-data-crawler"
COMP_CRAWLER="${RESOURCE_PREFIX}-comp-data-crawler"

aws glue start-crawler --name $SAP_CRAWLER 2>/dev/null && echo "[OK] Started $SAP_CRAWLER" || echo "[WARNING] Crawler $SAP_CRAWLER not found or already running"
aws glue start-crawler --name $COMP_CRAWLER 2>/dev/null && echo "[OK] Started $COMP_CRAWLER" || echo "[WARNING] Crawler $COMP_CRAWLER not found or already running"

echo "Waiting for crawlers to complete..."
while true; do
    SAP_STATE=$(aws glue get-crawler --name $SAP_CRAWLER --query 'Crawler.State' --output text 2>/dev/null)
    COMP_STATE=$(aws glue get-crawler --name $COMP_CRAWLER --query 'Crawler.State' --output text 2>/dev/null)
    if [ "$SAP_STATE" = "READY" ] && [ "$COMP_STATE" = "READY" ]; then
        echo "[OK] Crawlers completed"
        break
    fi
    echo "Crawlers still running (SAP: $SAP_STATE, Comp: $COMP_STATE)..."
    sleep 10
done

echo "Importing Glue views..."
VIEW_IMPORT_FUNCTION="${RESOURCE_PREFIX}GlueViewImport"
GLUE_CATALOG_BUCKET="glue-catalog-${ACCOUNT_ID}"
echo '{"bucket":"'$GLUE_CATALOG_BUCKET'","key":"glue_catalog_export.zip"}' > /tmp/view-import-payload.json
aws lambda invoke \
  --function-name $VIEW_IMPORT_FUNCTION \
  --cli-binary-format raw-in-base64-out \
  --payload file:///tmp/view-import-payload.json \
  /tmp/view-import-response.json
cat /tmp/view-import-response.json
echo ""
echo "[OK] Views imported"

echo "Starting Knowledge Base sync..."
KB_ID=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`SupplierKnowledgeBaseId`].OutputValue' --output text)
DS_ID_FULL=$(aws cloudformation describe-stacks --stack-name $STACK_NAME --query 'Stacks[0].Outputs[?OutputKey==`SupplierDataSourceId`].OutputValue' --output text)

# Extract just the DataSource ID (after the pipe if present)
case "$DS_ID_FULL" in
    *"|"*)
        DS_ID=$(echo $DS_ID_FULL | cut -d'|' -f2)
        ;;
    *)
        DS_ID=$DS_ID_FULL
        ;;
esac

if [ ! -z "$KB_ID" ] && [ ! -z "$DS_ID" ]; then
    echo "Starting ingestion job for KB: $KB_ID, DataSource: $DS_ID"
    SYNC_OUTPUT=$(aws bedrock-agent start-ingestion-job --knowledge-base-id $KB_ID --data-source-id $DS_ID 2>&1)
    if [ $? -eq 0 ]; then
        echo "[OK] Knowledge Base sync started"
    else
        echo "[WARNING] Failed to start KB sync: $SYNC_OUTPUT"
    fi
else
    echo "[WARNING] Knowledge Base IDs not found (KB_ID: $KB_ID, DS_ID: $DS_ID)"
fi

echo "Deploying Bedrock Agent..."
if [ -f "deploy_spa_multi_agent_system_v8.py" ]; then
    echo "Installing bedrock_agentcore_starter_toolkit..."
    pip install bedrock_agentcore_starter_toolkit --quiet
    python deploy_spa_multi_agent_system_v8.py \
      --s3-output-bucket s3://$ATHENA_BUCKET/ \
      --knowledge-base-id $KB_ID \
      --sap-url "$SAP_URL" \
      --secret-name $SECRET_NAME \
      --region $REGION \
      --model-id anthropic.claude-3-5-sonnet-20240620-v1:0 \
      --athena-database sapdatadb \
      --compliance-database compdatadb \
      --environment prod \
      --agent-name $AGENT_NAME \
      --cognito-user-pool-id $USER_POOL_ID \
      --cognito-client-id $USER_POOL_CLIENT_ID \
      --auto-update-on-conflict
    
    if [ $? -eq 0 ]; then
        echo "[OK] Bedrock Agent deployed successfully"
        
        # Extract agent ARN from deployment file or list agents
        if [ -f "${AGENT_NAME}_deployment.json" ]; then
            AGENT_RUNTIME_ARN=$(grep -o '"agent_arn": "[^"]*"' ${AGENT_NAME}_deployment.json | cut -d'"' -f4)
        else
            # Fallback: list agents and find by name
            AGENT_RUNTIME_ARN=$(aws bedrock-agentcore list-agent-runtimes --region $REGION --query "agentRuntimes[?contains(agentRuntimeArn, '$AGENT_NAME')].agentRuntimeArn" --output text | head -1)
        fi
        
        if [ -z "$AGENT_RUNTIME_ARN" ]; then
            echo "[WARNING] Could not determine agent ARN"
        else
            echo "Agent Runtime ARN: $AGENT_RUNTIME_ARN"
            
            # Update WebSocket Lambda with agent ARN
            echo "Updating WebSocket Lambda with agent ARN..."
            aws lambda update-function-configuration \
              --function-name ${RESOURCE_PREFIX}WebSocketLambda \
              --environment "Variables={AGENT_RUNTIME_ARN=$AGENT_RUNTIME_ARN,CONNECTIONS_TABLE=${RESOURCE_PREFIX}ConnectionsTable,VISUALIZATION_BUCKET=spa-code-interpreter-${ACCOUNT_ID}}" \
              > /dev/null
            echo "[OK] WebSocket Lambda updated"
        fi
    else
        echo "[WARNING] Failed to deploy Bedrock Agent"
    fi
else
    echo "[WARNING] deploy_spa_multi_agent_system_v8.py not found, skipping agent deployment"
fi

echo ""
echo "=== Deployment Complete ==="
echo "CloudFront URL: $CLOUDFRONT_URL"
echo "WebSocket URL: $WEBSOCKET_URL"
echo "SAP Data Bucket: s3://$SAP_DATA_BUCKET"
echo "Compliance Data Bucket: s3://$COMPLIANCE_DATA_BUCKET"
echo "Knowledge Base Bucket: s3://$KB_BUCKET"
echo "Athena Query Bucket: s3://$ATHENA_BUCKET"
echo "Knowledge Base ID: $KB_ID"
echo "Agent Name: $AGENT_NAME"
echo ""
echo "Glue crawlers started. Check status with:"
echo "  aws glue get-crawler --name $SAP_CRAWLER"
echo "  aws glue get-crawler --name $COMP_CRAWLER"