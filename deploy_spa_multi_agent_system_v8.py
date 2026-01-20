#!/usr/bin/env python3

"""
SPA Multi-Agent System v8 Deployment Script
============================================
This version includes INBOUND AUTHENTICATION using Amazon Cognito.

Key Changes from v7:
- Added Cognito User Pool integration for JWT-based authentication
- Requires --cognito-user-pool-id and --cognito-client-id parameters
- Configures AgentCore Runtime with customJWTAuthorizer
- Enables user-level authentication instead of IAM-only access

Usage:
    python deploy_spa_multi_agent_system_v8.py \\
      --s3-output-bucket s3://athena-query-bucket-YOUR_ACCOUNT_ID/ \\
      --knowledge-base-id YOUR_KB_ID \\
      --sap-url https://sapinsider2024.awsforsap.sap.aws.dev \\
      --secret-name SAPDEMOCRED \\
      --region us-east-1 \\
      --model-id us.anthropic.claude-sonnet-4-20250514-v1:0 \\
      --athena-database sapdatadb \\
      --compliance-database compdatadb \\
      --environment prod \\
      --agent-name spa_multi_agent_system_v8 \\
      --cognito-user-pool-id us-east-1_xxxxx \\
      --cognito-client-id your-app-client-id
"""

from bedrock_agentcore_starter_toolkit import Runtime
from boto3.session import Session
import time
import json
import boto3
import argparse
import os

def create_spa_multi_agent_execution_role(account_id, region):
    """Create execution role for SPA Multi-Agent System"""
    iam = boto3.client('iam')
    role_name = "spa_multi_agent_system_execution_role"
    policy_name = f"{role_name}_policy"

    print(f"Creating execution role: {role_name}")

    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": [
                        "bedrock-agentcore.amazonaws.com",
                        "lambda.amazonaws.com",
                        "ecs-tasks.amazonaws.com"
                    ]
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }

    permission_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "CloudWatchLogsDescribe",
                "Effect": "Allow",
                "Action": [
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams"
                ],
                "Resource": [
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/bedrock-agentcore/*",
                    f"arn:aws:logs:{region}:{account_id}:log-group:/aws/lambda/*",
                    f"arn:aws:logs:{region}:{account_id}:log-group:/ecs/*"
                ]
            },



            {
                "Sid": "BedrockAgentCoreAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateMemory",
                    "bedrock-agentcore:DeleteMemory",
                    "bedrock-agentcore:GetMemory",
                    "bedrock-agentcore:ListMemories",
                    "bedrock-agentcore:UpdateMemory",
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT"
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:memory/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:runtime/*",
                    f"arn:aws:bedrock-agentcore:{region}:{account_id}:workload-identity-directory/*"
                ]
            },
            {
                "Sid": "BedrockModelInvoke",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream"
                ],
                "Resource": [
                    f"arn:aws:bedrock:{region}::foundation-model/*",
                    f"arn:aws:bedrock:us-east-1::foundation-model/*"
                ]
            },
            {
                "Sid": "BedrockKnowledgeBaseAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock:Retrieve",
                    "bedrock:RetrieveAndGenerate"
                ],
                "Resource": f"arn:aws:bedrock:{region}:{account_id}:knowledge-base/*"
            },
            {
                "Sid": "CodeInterpreterAccess",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:StartCodeInterpreterSession",
                    "bedrock-agentcore:InvokeCodeInterpreter",
                    "bedrock-agentcore:StopCodeInterpreterSession"
                ],
                "Resource": "*"
            },

            {
                "Sid": "S3DeleteAccess",
                "Effect": "Allow",
                "Action": "s3:DeleteObject",
                "Resource": [
                    f"arn:aws:s3:::athena-query-bucket-{account_id}/*",
                    f"arn:aws:s3:::spa-code-interpreter-{account_id}/*",
                    f"arn:aws:s3:::sap-data-bucket-{account_id}/*",
                    f"arn:aws:s3:::comp-data-bucket-{account_id}/*"
                ]
            },
            {
                "Sid": "S3ListBucketAccess",
                "Effect": "Allow",
                "Action": [
                    "s3:ListBucket",
                    "s3:GetBucketLocation"
                ],
                "Resource": [
                    f"arn:aws:s3:::athena-query-bucket-{account_id}",
                    f"arn:aws:s3:::spa-code-interpreter-{account_id}",
                    f"arn:aws:s3:::sap-data-bucket-{account_id}",
                    f"arn:aws:s3:::comp-data-bucket-{account_id}"
                ]
            },
            {
                "Sid": "SecretsManagerAccess",
                "Effect": "Allow",
                "Action": [
                    "secretsmanager:GetSecretValue",
                    "secretsmanager:DescribeSecret"
                ],
                "Resource": [
                    f"arn:aws:secretsmanager:{region}:{account_id}:secret:*",
                    f"arn:aws:secretsmanager:{region}:{account_id}:secret:SAPDEMOCRED-*",
                    f"arn:aws:secretsmanager:{region}:{account_id}:secret:spa-sap-credentials-*"
                ]
            },
            {
                "Sid": "KMSDecryptAccess",
                "Effect": "Allow",
                "Action": [
                    "kms:Decrypt",
                    "kms:DescribeKey",
                    "kms:GenerateDataKey"
                ],
                "Resource": f"arn:aws:kms:{region}:{account_id}:key/*"
            },

        ]
    }

    try:
        # Create or get role
        try:
            role_response = iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
                Description="Execution role for SPA Multi-Agent System"
            )
            role_arn = role_response['Role']['Arn']
            print("[OK] Role created")
        except iam.exceptions.EntityAlreadyExistsException:
            role_response = iam.get_role(RoleName=role_name)
            role_arn = role_response['Role']['Arn']
            print("[OK] Using existing role")

        # Create or update policy
        policy_arn = f"arn:aws:iam::{account_id}:policy/{policy_name}"
        try:
            # Check if policy exists and manage versions
            policy_versions = iam.list_policy_versions(PolicyArn=policy_arn)
            if len(policy_versions['Versions']) >= 5:
                oldest = min([v for v in policy_versions['Versions'] if not v['IsDefaultVersion']],
                           key=lambda x: x['CreateDate'])
                iam.delete_policy_version(PolicyArn=policy_arn, VersionId=oldest['VersionId'])

            iam.create_policy_version(
                PolicyArn=policy_arn,
                PolicyDocument=json.dumps(permission_policy),
                SetAsDefault=True
            )
            print("[OK] Policy updated")
        except iam.exceptions.NoSuchEntityException:
            iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=json.dumps(permission_policy),
                Description="Permissions for SPA Multi-Agent System"
            )
            print("[OK] Policy created")

        # Attach custom policy to role
        try:
            iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
            print("[OK] Custom policy attached")
        except Exception as e:
            if "LimitExceeded" not in str(e):
                print(f"Policy attachment warning: {e}")
            else:
                print("[OK] Custom policy already attached")
        
        # Attach AWS managed policies
        managed_policies = [
            ("arn:aws:iam::aws:policy/AWSLambdaExecute", "AWSLambdaExecute"),
            ("arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess", "AWSAppRunnerServicePolicyForECRAccess"),
            ("arn:aws:iam::aws:policy/AmazonBedrockLimitedAccess", "AmazonBedrockLimitedAccess"),
            ("arn:aws:iam::aws:policy/AmazonAthenaFullAccess", "AmazonAthenaFullAccess")
        ]
        
        for policy_arn, policy_name in managed_policies:
            try:
                iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
                print(f"[OK] {policy_name} managed policy attached")
            except Exception as e:
                if "LimitExceeded" not in str(e):
                    print(f"{policy_name} attachment warning: {e}")
                else:
                    print(f"[OK] {policy_name} already attached")

        # Wait for IAM propagation
        print("[WAIT] Waiting for IAM propagation...")
        time.sleep(15)
        return role_arn

    except Exception as e:
        print(f"[ERROR] Error creating role: {e}")
        return None

def verify_s3_bucket(bucket_uri, region):
    """Verify S3 bucket exists and is accessible"""
    s3 = boto3.client('s3', region_name=region)
    
    # Extract bucket name from s3:// URI
    bucket_name = bucket_uri.replace('s3://', '').rstrip('/')
    
    print(f"Verifying S3 bucket: {bucket_name}")
    
    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f"[OK] Bucket {bucket_name} exists and is accessible")
        return True
    except Exception as e:
        print(f"[ERROR] Bucket {bucket_name} not accessible: {e}")
        return False

def create_code_interpreter_bucket(account_id, region):
    """Create S3 bucket for Code Interpreter output (idempotent)"""
    s3 = boto3.client('s3', region_name=region)
    bucket_name = f'spa-code-interpreter-{account_id}'
    
    print(f"Setting up Code Interpreter S3 bucket: {bucket_name}")
    
    try:
        # Check if bucket exists
        try:
            s3.head_bucket(Bucket=bucket_name)
            print("[OK] Using existing Code Interpreter bucket")
            return bucket_name
        except:
            pass
        
        # Create bucket
        if region == 'us-east-1':
            s3.create_bucket(Bucket=bucket_name)
        else:
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )
        print("[OK] Code Interpreter bucket created")
        
        # Enable CORS for frontend access
        s3.put_bucket_cors(
            Bucket=bucket_name,
            CORSConfiguration={
                'CORSRules': [{
                    'AllowedOrigins': ['*'],
                    'AllowedMethods': ['GET'],
                    'AllowedHeaders': ['*'],
                    'MaxAgeSeconds': 3000
                }]
            }
        )
        print("[OK] CORS configured")
        
        return bucket_name
        
    except Exception as e:
        print(f"[ERROR] Failed to create Code Interpreter bucket: {e}")
        raise

def create_new_spa_memory(region, environment):
    """Create a NEW memory every time during deployment"""
    try:
        print(f"Creating NEW SPA Memory for {environment}...")

        from bedrock_agentcore.memory import MemoryClient
        memory_client = MemoryClient(region_name=region)

        timestamp = int(time.time())
        memory_name = f"SPA_MultiAgent_{environment.upper()}_{timestamp}"

        print(f"[NEW] Creating memory: {memory_name}")

        memory_result = memory_client.create_memory_and_wait(
            name=memory_name,
            description=f"SPA Multi-Agent System Memory - {environment.upper()} - Created {timestamp}",
            strategies=[],
            event_expiry_days=30,
            max_wait=300,
            poll_interval=10
        )

        new_memory_id = memory_result['id']
        print(f"[OK] NEW Memory created successfully: {new_memory_id}")

        memory_client.get_memory(memoryId=new_memory_id)
        print(f"[OK] Memory verified and accessible: {new_memory_id}")

        return new_memory_id

    except Exception as e:
        print(f"[ERROR] Memory setup failed: {e}")
        raise

def update_agent_config(agent_file, config):
    """Update the agent file with configuration values"""
    print(f"Updating configuration in {agent_file}...")

    with open(agent_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # Use regex to replace os.getenv calls with or without defaults
    import re
    
    updated_content = content
    
    # Replace S3_OUTPUT_BUCKET (handles both with and without default)
    updated_content = re.sub(
        r"os\.getenv\('S3_OUTPUT_BUCKET'(?:,\s*'[^']*')?\)",
        f"'{config['s3_output_bucket']}'",
        updated_content
    )
    
    # Replace other config values
    replacements = {
        "os.getenv('AWS_REGION', 'us-east-1')": f"'{config['region']}'",
        "os.getenv('ATHENA_DATABASE', 'sapdatadb')": f"'{config.get('athena_database', 'sapdatadb')}'",
        "os.getenv('COMPLIANCE_DATABASE', 'compdatadb')": f"'{config.get('compliance_database', 'compdatadb')}'",
        "os.getenv('KNOWLEDGE_BASE_ID')": f"'{config['knowledge_base_id']}'",
        "os.getenv('SAP_URL')": f"'{config['sap_url']}'",
        "os.getenv('SECRET_NAME')": f"'{config['secret_name']}'",
        "os.getenv('MODEL_ID', 'us.anthropic.claude-sonnet-4-20250514-v1:0')": f"'{config['model_id']}'",
        "os.getenv('NOVA_MODEL_ID', 'amazon.nova-micro-v1:0')": f"'{config['nova_model_id']}'",
        "os.getenv('ENVIRONMENT', 'dev')": f"'{config.get('environment', 'prod')}'",
        "os.getenv('SPA_MEMORY_ID')": f"'{config.get('spa_memory_id', '')}'",
        "os.getenv('SPA_MEMORY_NAME')": f"'{config.get('spa_memory_name', '')}'",
        "os.getenv('CODE_INTERPRETER_BUCKET', 'spa-code-interpreter-output')": f"'{config.get('code_interpreter_bucket', 'spa-code-interpreter-output')}'",
        "os.getenv('GATEWAY_URL')": f"'{config.get('gateway_url', '')}'",
        "os.getenv('GATEWAY_COGNITO_CLIENT_ID')": f"'{config.get('gateway_cognito_client_id', '')}'",
        "os.getenv('GATEWAY_COGNITO_CLIENT_SECRET')": f"'{config.get('gateway_cognito_client_secret', '')}'",
        "os.getenv('GATEWAY_TOKEN_URL')": f"'{config.get('gateway_token_url', '')}'",
    }

    for old, new in replacements.items():
        updated_content = updated_content.replace(old, new)

    configured_agent_file = "spa_multi_agent_system_configured.py"

    with open(configured_agent_file, 'w', encoding='utf-8') as f:
        f.write(updated_content)

    print(f"[OK] Configuration updated and saved to {configured_agent_file}")
    return configured_agent_file

def create_requirements_file():
    """Create requirements.txt file for the agent"""
    requirements_content = """strands-agents
strands-agents-tools
uv
boto3>=1.34.0
botocore>=1.34.0
bedrock-agentcore
bedrock-agentcore-starter-toolkit
requests>=2.31.0
python-dateutil>=2.8.0
jsonschema>=4.0.0
pydantic>=2.0.0
mcp
"""
    
    requirements_file = "requirements.txt"
    
    if not os.path.exists(requirements_file):
        with open(requirements_file, 'w', encoding='utf-8') as f:
            f.write(requirements_content)
        print(f"[OK] Created {requirements_file}")
    else:
        print(f"[OK] Using existing {requirements_file}")
    
    return requirements_file

def cleanup_temp_files(files_to_cleanup):
    """Clean up temporary files"""
    for file_path in files_to_cleanup:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[CLEANUP] Cleaned up: {file_path}")
        except Exception as e:
            print(f"[WARNING] Could not cleanup {file_path}: {e}")

def main():
    """Deploy SPA Multi-Agent System v8 with Cognito Inbound Auth"""
    
    parser = argparse.ArgumentParser(description='Deploy SPA Multi-Agent System v8 with Cognito Inbound Authentication')
    parser.add_argument('--s3-output-bucket', required=True, help='S3 bucket for Athena query results')
    parser.add_argument('--knowledge-base-id', required=True, help='Bedrock Knowledge Base ID')
    parser.add_argument('--sap-url', required=True, help='SAP system URL')
    parser.add_argument('--secret-name', default='spa-sap-credentials-prod', help='AWS Secrets Manager secret name')
    parser.add_argument('--region', default='us-east-1', help='AWS region')
    parser.add_argument('--model-id', default='us.anthropic.claude-sonnet-4-20250514-v1:0', help='Primary model ID')
    parser.add_argument('--nova-model-id', default='amazon.nova-micro-v1:0', help='Nova model ID')
    parser.add_argument('--athena-database', default='sapdatadb', help='Athena database name')
    parser.add_argument('--compliance-database', default='compdatadb', help='Compliance database name')
    parser.add_argument('--environment', default='prod', help='Environment (dev/staging/prod)')
    parser.add_argument('--agent-name', default='spa-multi-agent-system-v8', help='Agent name')
    
    # NEW: Cognito parameters for Inbound Auth
    parser.add_argument('--cognito-user-pool-id', required=True, help='Cognito User Pool ID (e.g., us-east-1_xxxxx)')
    parser.add_argument('--cognito-client-id', required=True, help='Cognito App Client ID')
    parser.add_argument('--auto-update-on-conflict', action='store_true', help='Auto-update agent if it already exists')
    
    # Gateway parameters for MCP
    parser.add_argument('--gateway-url', help='Gateway MCP URL (e.g., https://xxx.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp)')
    parser.add_argument('--gateway-cognito-client-id', help='Gateway Cognito Client ID for OAuth2')
    parser.add_argument('--gateway-cognito-client-secret', help='Gateway Cognito Client Secret for OAuth2')
    parser.add_argument('--gateway-token-url', help='Gateway Cognito Token URL')
    
    args = parser.parse_args()
    
    original_agent_file = "spa_multi_agent_system_v8.py"
    cleanup_files = []
    
    print("[DEPLOY] Deploying SPA Multi-Agent System v8 with Cognito Inbound Auth")
    print("=" * 80)
    print(f"[AUTH] INBOUND AUTHENTICATION: ENABLED (Cognito)")
    print(f"Agent Name: {args.agent_name}")
    print(f"Environment: {args.environment}")
    print(f"Cognito User Pool: {args.cognito_user_pool_id}")
    print(f"Cognito Client ID: {args.cognito_client_id}")
    print("=" * 80)
    
    if not os.path.exists(original_agent_file):
        print(f"[ERROR] Agent file {original_agent_file} not found!")
        return
    
    try:
        account_id = boto3.client('sts').get_caller_identity()['Account']
        print(f"[OK] AWS Account ID: {account_id}")
    except Exception as e:
        print(f"[ERROR] Failed to get AWS credentials: {e}")
        return
    
    # Step 1: Verify S3 output bucket
    print("\n1. Verifying S3 output bucket...")
    if not verify_s3_bucket(args.s3_output_bucket, args.region):
        print(f"[ERROR] S3 output bucket {args.s3_output_bucket} does not exist or is not accessible")
        print(f"[ERROR] Please create the bucket first or check permissions")
        return
    
    # Step 2: Create execution role
    print("\n2. Creating execution role...")
    role_arn = create_spa_multi_agent_execution_role(account_id, args.region)
    if not role_arn:
        return
   
    # Step 3: Create Code Interpreter bucket
    print("\n3. Setting up Code Interpreter S3 bucket...")
    try:
        code_interpreter_bucket = create_code_interpreter_bucket(account_id, args.region)
    except Exception as e:
        print(f"[ERROR] Code Interpreter bucket setup failed: {e}")
        return
    
    # Step 4: Create memory
    print("\n4. Creating NEW SPA Memory...")
    try:
        spa_memory_id = create_new_spa_memory(args.region, args.environment)
        spa_memory_name = f"SPA_MultiAgent_{args.environment.upper()}_{int(time.time())}"
    except Exception as e:
        print(f"[ERROR] Memory creation failed: {e}")
        return

    # Step 5: Create requirements
    print("\n5. Setting up requirements...")
    requirements_file = create_requirements_file()
    
    # Step 6: Update agent config
    print("\n6. Updating agent configuration...")
    print(f"[DEBUG] S3 Output Bucket: {args.s3_output_bucket}")
    config = {
        'region': args.region,
        's3_output_bucket': args.s3_output_bucket,
        'athena_database': args.athena_database,
        'compliance_database': args.compliance_database,
        'knowledge_base_id': args.knowledge_base_id,
        'sap_url': args.sap_url,
        'secret_name': args.secret_name,
        'model_id': args.model_id,
        'nova_model_id': args.nova_model_id,
        'environment': args.environment,
        'spa_memory_id': spa_memory_id,
        'spa_memory_name': spa_memory_name,
        'code_interpreter_bucket': code_interpreter_bucket,
        'gateway_url': args.gateway_url or '',
        'gateway_cognito_client_id': args.gateway_cognito_client_id or '',
        'gateway_cognito_client_secret': args.gateway_cognito_client_secret or '',
        'gateway_token_url': args.gateway_token_url or ''
    }
    
    configured_agent_file = update_agent_config(original_agent_file, config)
    cleanup_files.append(configured_agent_file)
    
    # Verify the configuration was applied
    print("[DEBUG] Verifying configured file...")
    with open(configured_agent_file, 'r', encoding='utf-8') as f:
        config_content = f.read()
        if args.s3_output_bucket in config_content:
            print(f"[OK] S3 bucket correctly configured: {args.s3_output_bucket}")
        else:
            print(f"[WARNING] S3 bucket may not be configured correctly")
    
    # Step 7: Configure runtime with Cognito auth
    print("\n7. Configuring AgentCore Runtime with Cognito Inbound Auth...")
    try:
        agentcore_runtime = Runtime()
        
        # NEW: Build Cognito discovery URL
        discovery_url = f"https://cognito-idp.{args.region}.amazonaws.com/{args.cognito_user_pool_id}/.well-known/openid-configuration"
        
        print(f"[AUTH] Cognito Discovery URL: {discovery_url}")
        print(f"[AUTH] Allowed Client: {args.cognito_client_id}")
        
        agentcore_runtime.configure(
            entrypoint=configured_agent_file,
            execution_role=role_arn,
            auto_create_ecr=True,
            requirements_file=requirements_file,
            region=args.region,
            agent_name=args.agent_name,
            # NEW: Cognito Inbound Auth configuration
            authorizer_configuration={
                "customJWTAuthorizer": {
                    "discoveryUrl": discovery_url,
                    "allowedClients": [args.cognito_client_id]
                }
            }
        )
        print(f"[OK] Agent configured with Cognito Inbound Auth and Memory ID: {spa_memory_id}")
        print("[OK] Agent configured with Cognito Inbound Auth")
    except Exception as e:
        print(f"[ERROR] Configuration failed: {e}")
        cleanup_temp_files(cleanup_files)
        return
    
    # Step 7: Launch
    print(f"\n8. Launching {args.agent_name}...")
    try:
        launch_result = agentcore_runtime.launch(auto_update_on_conflict=args.auto_update_on_conflict)
        print("[OK] Agent launch initiated")
        print(f"Agent ARN: {launch_result.agent_arn}")
        print(f"Agent ID: {launch_result.agent_id}")
    except Exception as e:
        print(f"[ERROR] Launch failed: {e}")
        cleanup_temp_files(cleanup_files)
        return
    
    # Step 8: Monitor status
    print(f"\n9. Monitoring deployment...")
    status = "CREATING"
    max_attempts = 60
    attempt = 0
    
    while attempt < max_attempts:
        try:
            status_response = agentcore_runtime.status()
            status = status_response.endpoint.get('status', 'UNKNOWN')
            print(f"Attempt {attempt + 1}/{max_attempts} - Status: {status}")
            
            if status == 'READY':
                print("[SUCCESS] Deployment successful!")
                break
            elif status in ['CREATE_FAILED', 'DELETE_FAILED', 'UPDATE_FAILED', 'FAILED']:
                print(f"[ERROR] Deployment failed: {status}")
                cleanup_temp_files(cleanup_files)
                return
            
            attempt += 1
            if attempt < max_attempts:
                time.sleep(30)
                
        except Exception as e:
            print(f"Status check error: {e}")
            attempt += 1
            if attempt < max_attempts:
                time.sleep(30)
    
    if status != 'READY':
        print(f"[ERROR] Deployment timed out: {status}")
        cleanup_temp_files(cleanup_files)
        return
    
    # Step 9: Save deployment info
    print("\n10. Saving deployment info...")
    deployment_info = {
        "agent_name": args.agent_name,
        "agent_arn": launch_result.agent_arn,
        "agent_id": launch_result.agent_id,
        "environment": args.environment,
        "inbound_auth": {
            "type": "Cognito JWT",
            "user_pool_id": args.cognito_user_pool_id,
            "client_id": args.cognito_client_id,
            "discovery_url": discovery_url
        },
        "spa_memory_id": spa_memory_id,
        "configuration": config
    }
    
    deployment_file = f"{args.agent_name}_deployment.json"
    with open(deployment_file, "w", encoding='utf-8') as f:
        json.dump(deployment_info, f, indent=2)
    
    # Success message
    print("\n" + "=" * 80)
    print("[SUCCESS] SPA Multi-Agent System v8 Successfully Deployed!")
    print("=" * 80)
    print(f"[AUTH] Inbound Auth: ENABLED (Cognito)")
    print(f"Agent ARN: {launch_result.agent_arn}")
    print(f"Memory ID: {spa_memory_id}")
    print(f"Deployment Info: {deployment_file}")
    
    cleanup_temp_files(cleanup_files)

if __name__ == "__main__":
    main()
