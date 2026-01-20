#!/usr/bin/env python3
import boto3
import json
import sys
import subprocess
import tempfile
import os
import uuid
import time

def create_gateway_role(lambda_arn, aws_region='us-east-1'):
    """Create IAM role for gateway invocation"""
    iam = boto3.client('iam', region_name=aws_region)
    sts = boto3.client('sts', region_name=aws_region)
    account_id = sts.get_caller_identity()['Account']
    role_name = "rfq-gateway-invoke-role"
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        response = iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
        role_arn = response['Role']['Arn']
        print(f"✅ Created role: {role_arn}")
    except iam.exceptions.EntityAlreadyExistsException:
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
        print(f"📋 Role already exists: {role_arn}")
    
    policy_doc = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": "lambda:InvokeFunction",
            "Resource": lambda_arn
        }]
    }
    
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="LambdaInvokePolicy",
        PolicyDocument=json.dumps(policy_doc)
    )
    
    print("⏳ Waiting for IAM role to propagate...")
    time.sleep(10)
    
    return role_arn

def create_gateway(lambda_arn, cognito_user_pool_id, cognito_client_id, aws_region='us-east-1'):
    """Create Bedrock AgentCore Gateway with CUSTOM_JWT authentication"""
    
    # Create IAM role
    role_arn = create_gateway_role(lambda_arn, aws_region)
    gateway_name = f"RFQGateway-{uuid.uuid4().hex[:8]}"
    
    # Create JWT authorizer configuration
    discovery_url = f"https://cognito-idp.{aws_region}.amazonaws.com/{cognito_user_pool_id}/.well-known/openid-configuration"
    authorizer_config = {
        "customJWTAuthorizer": {
            "allowedClients": [cognito_client_id],
            "discoveryUrl": discovery_url
        }
    }
    
    try:
        # Create gateway with CUSTOM_JWT authentication
        cmd = f"""aws bedrock-agentcore-control create-gateway --name {gateway_name} --role-arn {role_arn} --protocol-type MCP --authorizer-type CUSTOM_JWT --authorizer-configuration '{json.dumps(authorizer_config)}' --region {aws_region}"""
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Error creating gateway: {result.stderr}")
            sys.exit(1)
        
        gateway_data = json.loads(result.stdout)
        gateway_id = gateway_data['gatewayId']
        gateway_url = f"https://{gateway_id}.gateway.bedrock-agentcore.{aws_region}.amazonaws.com"
        print(f"✅ Gateway created with CUSTOM_JWT: {gateway_id}")
        print(f"📋 Gateway URL: {gateway_url}")
        
        # Wait for gateway to be READY
        print("⏳ Waiting for gateway to be ready...")
        max_wait = 60
        wait_count = 0
        while wait_count < max_wait:
            check_cmd = f"aws bedrock-agentcore-control get-gateway --gateway-identifier {gateway_id} --region {aws_region}"
            check_result = subprocess.run(check_cmd, shell=True, capture_output=True, text=True)
            if check_result.returncode == 0:
                gateway_status = json.loads(check_result.stdout).get('status')
                if gateway_status == 'READY':
                    print(f"✅ Gateway is ready")
                    break
                print(f"   Gateway status: {gateway_status}")
            time.sleep(5)
            wait_count += 5
        
        if wait_count >= max_wait:
            print(f"⚠️ Gateway creation timeout, but continuing...")
            
    except Exception as e:
        print(f"❌ Error creating gateway: {e}")
        sys.exit(1)
    
    # Create target configuration
    target_config = {
        "mcp": {
            "lambda": {
                "lambdaArn": lambda_arn,
                "toolSchema": {
                    "inlinePayload": [{
                        "name": "create_rfq",
                        "description": "Create RFQ in SAP system",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "material_number": {"type": "string"},
                                "supplier_id": {"type": "string"},
                                "quantity": {"type": "string"},
                                "delivery_date": {"type": "string"},
                                "rfq_name": {"type": "string"}
                            },
                            "required": ["material_number", "supplier_id", "quantity", "delivery_date"]
                        }
                    }]
                }
            }
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(target_config, f)
        target_file = f.name
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump([{"credentialProviderType": "GATEWAY_IAM_ROLE"}], f)
        cred_file = f.name
    
    try:
        cmd = f"""aws bedrock-agentcore-control create-gateway-target --gateway-identifier {gateway_id} --name RFQTarget --target-configuration file://{target_file} --credential-provider-configurations file://{cred_file} --region {aws_region}"""
        
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"❌ Error creating target: {result.stderr}")
            sys.exit(1)
        
        gateway_arn = f"arn:aws:bedrock-agentcore:{aws_region}:{boto3.client('sts').get_caller_identity()['Account']}:gateway/{gateway_id}"
        
        print(f"✅ Gateway target created successfully!")
        print(f"Gateway ARN: {gateway_arn}")
        print(f"Gateway ID: {gateway_id}")
        print(f"Gateway URL: {gateway_url}")
        print(f"MCP URL: {gateway_url}/mcp")
        
        # Add Lambda permission for Gateway to invoke Lambda
        print(f"Adding Lambda permission for Gateway...")
        lambda_client = boto3.client('lambda', region_name=aws_region)
        try:
            lambda_client.add_permission(
                FunctionName=lambda_arn,
                StatementId=f'AllowBedrockAgentCore-{gateway_id}',
                Action='lambda:InvokeFunction',
                Principal='bedrock-agentcore.amazonaws.com',
                SourceArn=gateway_arn
            )
            print(f"✅ Lambda permission added")
        except lambda_client.exceptions.ResourceConflictException:
            print(f"📋 Lambda permission already exists")
        
        # Save gateway config to file for deploy.sh
        gateway_config = {
            "gateway_id": gateway_id,
            "gateway_url": f"{gateway_url}/mcp",
            "gateway_arn": gateway_arn
        }
        with open('gateway_config.json', 'w') as f:
            json.dump(gateway_config, f, indent=2)
        print(f"💾 Gateway config saved to gateway_config.json")
        
        return gateway_arn, gateway_id
    finally:
        os.unlink(target_file)
        os.unlink(cred_file)

if __name__ == "__main__":
    if len(sys.argv) != 5:
        print("Usage: python create_gateway.py <lambda_arn> <cognito_user_pool_id> <cognito_client_id> <aws_region>")
        sys.exit(1)
    
    lambda_arn = sys.argv[1]
    cognito_user_pool_id = sys.argv[2]
    cognito_client_id = sys.argv[3]
    aws_region = sys.argv[4]
    
    create_gateway(lambda_arn, cognito_user_pool_id, cognito_client_id, aws_region)
