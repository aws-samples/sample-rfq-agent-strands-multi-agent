#!/bin/bash

set -e

STACK_NAME="rfq-assistant-stack"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGION=$(aws configure get region || echo "us-east-1")

echo "=== RFQ Assistant Complete Cleanup ==="
echo "Account ID: $ACCOUNT_ID"
echo "Region: $REGION"
echo ""

# 1. Delete Bedrock AgentCore Agents (from deployment file)
echo ""
echo "1. Deleting Bedrock AgentCore agents..."
for DEPLOY_FILE in *_deployment.json; do
    if [ -f "$DEPLOY_FILE" ]; then
        AGENT_ARN=$(jq -r '.agent_arn // empty' "$DEPLOY_FILE" 2>/dev/null)
        if [ ! -z "$AGENT_ARN" ]; then
            AGENT_ID=$(echo $AGENT_ARN | rev | cut -d'/' -f1 | rev)
            echo "  Deleting agent from $DEPLOY_FILE: $AGENT_ID"
            aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-arn $AGENT_ARN --region $REGION 2>/dev/null || echo "  Failed to delete $AGENT_ID"
        fi
    fi
done
if [ ! -f *_deployment.json 2>/dev/null ]; then
    echo "  No deployment files found"
fi

# 2. Delete Bedrock AgentCore Memories (from deployment file)
echo ""
echo "2. Deleting Bedrock AgentCore memories..."
for DEPLOY_FILE in *_deployment.json; do
    if [ -f "$DEPLOY_FILE" ]; then
        MEMORY_ID=$(jq -r '.spa_memory_id // empty' "$DEPLOY_FILE" 2>/dev/null)
        if [ ! -z "$MEMORY_ID" ]; then
            echo "  Deleting memory from $DEPLOY_FILE: $MEMORY_ID"
            aws bedrock-agentcore-control delete-memory --memory-id $MEMORY_ID --region $REGION 2>/dev/null || echo "  Failed to delete $MEMORY_ID"
        fi
    fi
done
if [ ! -f *_deployment.json 2>/dev/null ]; then
    echo "  No deployment files found"
fi

# 3. Delete ECR Repositories
echo ""
echo "3. Deleting ECR repositories..."
ECR_REPOS=$(aws ecr describe-repositories --region $REGION --query 'repositories[?contains(repositoryName, `bedrock-agentcore`)].repositoryName' --output text 2>/dev/null || echo "")
if [ ! -z "$ECR_REPOS" ]; then
    for REPO in $ECR_REPOS; do
        echo "  Deleting ECR repository: $REPO"
        aws ecr delete-repository --repository-name $REPO --force --region $REGION 2>/dev/null || echo "  Failed to delete $REPO"
    done
else
    echo "  No ECR repositories found"
fi

# 4. Empty and delete S3 buckets
echo ""
echo "4. Emptying and deleting S3 buckets..."
for BUCKET in \
    "sapdata-${ACCOUNT_ID}" \
    "compliancedata-${ACCOUNT_ID}" \
    "spa-table-structure-query-${ACCOUNT_ID}" \
    "chatapp-lambda-layers-${ACCOUNT_ID}" \
    "athena-query-bucket-${ACCOUNT_ID}" \
    "spa-code-interpreter-${ACCOUNT_ID}" \
    "glue-catalog-${ACCOUNT_ID}" \
    "react-chat-app-bucket-${ACCOUNT_ID}"; do
    if aws s3 ls "s3://$BUCKET" 2>/dev/null; then
        echo "  Emptying bucket: $BUCKET"
        aws s3 rm "s3://$BUCKET" --recursive 2>/dev/null || echo "  Failed to empty $BUCKET"
        echo "  Deleting bucket: $BUCKET"
        aws s3 rb "s3://$BUCKET" 2>/dev/null || echo "  Failed to delete $BUCKET"
    else
        echo "  Bucket not found: $BUCKET"
    fi
done

# 5. Delete IAM roles and policies
echo ""
echo "5. Deleting IAM roles and policies..."
ROLE_NAME="spa_multi_agent_system_execution_role"
POLICY_NAME="${ROLE_NAME}_policy"
POLICY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${POLICY_NAME}"

# Detach managed policies
for POLICY in \
    "arn:aws:iam::aws:policy/AWSLambdaExecute" \
    "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess" \
    "arn:aws:iam::aws:policy/AmazonBedrockLimitedAccess" \
    "arn:aws:iam::aws:policy/AmazonAthenaFullAccess"; do
    aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn $POLICY 2>/dev/null || true
done

# Detach and delete custom policy
aws iam detach-role-policy --role-name $ROLE_NAME --policy-arn $POLICY_ARN 2>/dev/null || true
aws iam delete-policy --policy-arn $POLICY_ARN 2>/dev/null || echo "  Policy not found: $POLICY_NAME"

# Delete role
aws iam delete-role --role-name $ROLE_NAME 2>/dev/null || echo "  Role not found: $ROLE_NAME"

# 6. Delete Glue databases
echo ""
echo "6. Deleting Glue databases..."
for DB in "sapdatadb" "compdatadb"; do
    if aws glue get-database --name $DB --region $REGION 2>/dev/null; then
        echo "  Deleting Glue database: $DB"
        # Delete all tables first
        TABLES=$(aws glue get-tables --database-name $DB --region $REGION --query 'TableList[].Name' --output text 2>/dev/null || echo "")
        if [ ! -z "$TABLES" ]; then
            for TABLE in $TABLES; do
                echo "    Deleting table: $TABLE"
                aws glue delete-table --database-name $DB --name $TABLE --region $REGION 2>/dev/null || true
            done
        fi
        # Delete database
        aws glue delete-database --name $DB --region $REGION 2>/dev/null || echo "  Failed to delete $DB"
    else
        echo "  Database not found: $DB"
    fi
done

# 7. Delete CodeBuild projects
echo ""
echo "7. Deleting CodeBuild projects..."
CODEBUILD_PROJECTS=$(aws codebuild list-projects --region $REGION --query 'projects[?contains(@, `bedrock-agentcore`)]' --output text 2>/dev/null || echo "")
if [ ! -z "$CODEBUILD_PROJECTS" ]; then
    for PROJECT in $CODEBUILD_PROJECTS; do
        echo "  Deleting CodeBuild project: $PROJECT"
        aws codebuild delete-project --name $PROJECT --region $REGION 2>/dev/null || echo "  Failed to delete $PROJECT"
    done
else
    echo "  No CodeBuild projects found"
fi

# 8. Delete CloudFormation stack
echo ""
echo "8. Deleting CloudFormation stack..."
if aws cloudformation describe-stacks --stack-name $STACK_NAME --region $REGION 2>/dev/null; then
    echo "  Deleting stack: $STACK_NAME"
    aws cloudformation delete-stack --stack-name $STACK_NAME --region $REGION
    echo "  Stack deletion initiated (will complete in background)"
else
    echo "  Stack not found: $STACK_NAME"
fi

# 9. Clean up local files
echo ""
echo "9. Cleaning up local files..."
rm -f .bedrock_agentcore.yaml
rm -f *_deployment.json
rm -f spa_multi_agent_system_configured.py
rm -f python-jose-layer.zip
rm -f opensearch-layer.zip
rm -rf lambda_layer
rm -rf opensearch_layer
rm -rf build
rm -rf node_modules
echo "  Local files cleaned"

echo ""
echo "=== Cleanup Complete ==="
echo "All resources have been deleted."