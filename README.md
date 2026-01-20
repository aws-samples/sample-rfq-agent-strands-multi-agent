# RFQ Assistant - Intelligent Supplier Performance Analysis System

> **⚠️ IMPORTANT NOTICE**: Sample code, software libraries, command line tools, proofs of concept, templates, or other related technology are provided as AWS Content or Third-Party Content under the AWS Customer Agreement, or the relevant written agreement between you and AWS (whichever applies). You should not use this AWS Content or Third-Party Content in your production accounts, or on production or other critical data. You are responsible for testing, securing, and optimizing the AWS Content or Third-Party Content, such as sample code, as appropriate for production grade use based on your specific quality control practices and standards. Deploying AWS Content or Third-Party Content may incur AWS charges for creating or using AWS chargeable resources, such as running Amazon EC2 instances or using Amazon S3 storage.

An AI-powered assistant for supplier performance analysis, RFQ creation, and compliance management built with Amazon Bedrock AgentCore and Strands Agents SDK.

## Overview

RFQ Assistant is a comprehensive multi-agent system that helps procurement teams analyze supplier performance, check compliance, create RFQs, and visualize data insights through natural language conversations.

## Features

### 🤖 Intelligent Agent Capabilities
- **RFQ Creation**: Automated Request for Quotation generation with SAP integration via Bedrock AgentCore Gateway
- **Supplier Performance Analysis**: Financial metrics, quality scores, and delivery performance
- **Compliance Checking**: REACH, ROHS, CMRT, and RBA compliance verification
- **Data Visualization**: Dynamic chart generation with Python code interpreter
- **Knowledge Base Integration**: Schema and table structure queries via Bedrock Knowledge Base
- **Conversational Memory**: Persistent context across sessions per user
- **MCP Integration**: Model Context Protocol for external tool integration via Gateway

### 🔐 Security & Authentication
- **Cognito Authentication**: JWT-based user authentication with Amazon Cognito
- **Gateway OAuth2**: Separate Cognito User Pool for Gateway JWT authentication
- **IAM Role-Based Access**: Fine-grained permissions for AWS services
- **WebSocket Security**: Secure real-time communication with API Gateway
- **WAF Protection**: Rate limiting and common attack prevention

### 📊 Data Integration
- **Amazon Athena**: SQL queries on SAP and compliance data
- **AWS Glue**: Automated data cataloging and schema management
- **S3 Data Lakes**: Scalable storage for SAP, compliance, and knowledge base data
- **SAP Integration**: Direct RFQ creation in SAP systems via Lambda function exposed through Gateway
- **Bedrock AgentCore Gateway**: MCP-based tool integration for external system connectivity

### 🎨 Modern Frontend
- **React SPA**: Responsive single-page application
- **Real-time Streaming**: WebSocket-based agent responses
- **CloudFront CDN**: Global content delivery with caching
- **Amplify UI**: Pre-built authentication components

## Architecture

![RFQ Assistant Architecture](blog/img/Architecture.png)

## Prerequisites

- **AWS Account** with appropriate permissions
- **AWS CLI** configured with credentials
- **Python 3.12+** installed
- **Node.js 18+** and npm installed
- **Bash shell** (Linux/macOS/WSL/Git Bash)

## Quick Start

### 1. Clone and Setup

```bash
cd sample-rfq-agent-strands-multi-agent
```

### 2. Deploy the System

```bash
bash deploy.sh
```

**Deployment Prompts:**

The script will ask for the following inputs:

1. **Enter SAP URL**: 
   - Your SAP system URL (e.g., `https://your-sap-system.com`)
   - Press **Enter** to skip if you don't have SAP integration
   - Used for real RFQ creation in SAP (optional)

2. **Enter Agent Name**: 
   - Name for your Bedrock agent (e.g., `rfq_agent`)
   - Press **Enter** to use default: `spa_multi_agent_system`
   - This name appears in AWS console and logs

3. **Enter AWS Secrets Manager Secret Name**: 
   - Name for storing SAP credentials (e.g., `SAPDEMOCRED`)
   - Press **Enter** to use default: `SAPDEMOCRED`
   - Secret is created automatically (empty initially)

**Deployment Time**: ~15-20 minutes

### 4. Post-Deployment Steps

#### A. Find Your CloudFront URL

After deployment completes, the script outputs:
```
=== Deployment Complete ===
CloudFront URL: https://d1234abcd5678.cloudfront.net
WebSocket URL: wss://abc123xyz.execute-api.us-east-1.amazonaws.com/prod
Knowledge Base ID: BE9HMVEZTY
Agent Name: rfq_agent
```

**Copy the CloudFront URL** - this is your application URL.

Alternatively, find it in AWS Console:
1. Go to **CloudFormation** → **rfq-assistant-stack** → **Outputs** tab
2. Look for **CloudFrontURL** output value

#### B. Configure SAP Credentials (Optional)

If you want real SAP RFQ creation, update the Secrets Manager secret:

**Option 1: AWS Console**
1. Go to **AWS Secrets Manager** console
2. Find secret named `SAPDEMOCRED` (or your custom name)
3. Click **Retrieve secret value** → **Edit**
4. Replace with:
   ```json
   {
     "SAPUSER": "your-sap-username",
     "SAPPASSWORD": "your-sap-password"
   }
   ```
5. Click **Save**

**Option 2: AWS CLI**
```bash
aws secretsmanager put-secret-value \
  --secret-id SAPDEMOCRED \
  --secret-string '{"SAPUSER":"your-username","SAPPASSWORD":"your-password"}'
```

**Note**: Without SAP credentials, RFQs are created in demo mode (simulated).

#### C. Create Your First User

1. Open the **CloudFront URL** in your browser
2. Click **Create Account**
3. Enter:
   - Email address
   - Password (min 8 characters)
4. Check email for verification code
5. Enter verification code
6. Sign in with your credentials

### 5. Test the Agent

Try these example queries:

```
"Show me vendors for material MZ-RM-C900-06"
"Check compliance for vendor USSU-VSF01"
"Create RFQ for material MZ-RM-M500-04 to vendor USSU-VSF08, quantity 10, delivery 2025-10-10"
"Generate a bar chart of top 5 vendors by quality score"
```

## What Gets Deployed

The deployment script automatically creates:

### Infrastructure (CloudFormation)
- ✅ S3 buckets for data, web hosting, and artifacts
- ✅ CloudFront distribution with WAF
- ✅ Cognito User Pool for authentication
- ✅ API Gateway WebSocket API
- ✅ Lambda functions (WebSocket handler, authorizer)
- ✅ DynamoDB table for connection management
- ✅ Bedrock Knowledge Base with OpenSearch Serverless
- ✅ AWS Glue crawlers and databases
- ✅ IAM roles and policies

### Agent (Bedrock AgentCore)
- ✅ Strands-based multi-agent system
- ✅ Persistent memory per user
- ✅ 7 built-in tools (compliance, financial, quality, visualization, etc.)
- ✅ MCP tools loaded from Gateway (RFQ creation)
- ✅ Bedrock AgentCore Gateway with CUSTOM_JWT authorizer
- ✅ Lambda function for SAP RFQ creation
- ✅ Code interpreter for visualizations
- ✅ OAuth2 client credentials flow for Gateway authentication

### Data
- ✅ Sample SAP data (purchase orders, vendors, materials)
- ✅ Sample compliance data (REACH, ROHS, CMRT, RBA)
- ✅ Knowledge base data (table schemas)
- ✅ Glue catalog views

## Usage Examples

### Create an RFQ
```
User: Create RFQ for material MZ-RM-C900-06 to vendor USSU-VSF01
Agent: I need quantity, delivery date, and optionally an RFQ name.

User: 10, 2025-10-10, Q4_Procurement
Agent: ✅ RFQ Created Successfully!
      RFQ Number: RFQ-20250210-A3F8B2C1
      RFQ Name: Q4_Procurement
      ...
```

### Check Compliance
```
User: Check compliance for vendors USSU-VSF01, USSU-VSF08
Agent: [Returns compliance table with REACH, ROHS, CMRT, RBA status]
```

### Analyze Supplier Performance
```
User: Show financial performance for material MZ-RM-M500-04
Agent: [Returns vendor rankings with financial scores]
```

### Generate Visualizations
```
User: Create a bar chart of top 5 vendors by quality score for material MZ-RM-C900-06
Agent: [Generates Python code, executes it, returns chart image]
```

## Configuration

### Update Model

To use a different model, edit `deploy.sh` and find the `--model-id` parameter (around line 235):

```bash
# Current default:
--model-id anthropic.claude-3-5-sonnet-20240620-v1:0

# Change to Claude 3.7 Sonnet (latest):
--model-id us.anthropic.claude-3-7-sonnet-20250219-v1:0

# Or use Claude 3.5 Haiku for lower cost:
--model-id anthropic.claude-3-5-haiku-20241022-v1:0
```

Then redeploy:
```bash
bash destroy.sh
bash deploy.sh
```

### SAP Integration (Optional)

To enable real SAP RFQ creation:

1. Store SAP credentials in Secrets Manager:
```bash
aws secretsmanager put-secret-value \
  --secret-id SAPDEMOCRED \
  --secret-string '{"SAPUSER":"your-user","SAPPASSWORD":"your-password"}'
```

2. Provide SAP URL during deployment when prompted

### Memory Configuration

Memory is automatically configured per user with:
- **Session ID**: `spa-persistent-{user_id}`
- **Context Turns**: Last 10 conversation turns
- **Expiry**: 30 days

## Advanced Features

### Multi-Agent Architecture
Built with Strands Agents SDK, the system uses:
- **Memory Hooks**: Automatic context injection and storage
- **Tool Selection**: Intelligent routing to specialized tools
- **Streaming Responses**: Real-time token-by-token output
- **Error Handling**: Graceful degradation and retry logic

### Code Interpreter
Executes Python code in sandboxed environment:
- Matplotlib for visualizations
- Pandas for data analysis
- Automatic S3 upload for charts
- Pre-signed URL generation

### Knowledge Base
Vector search over table schemas:
- Amazon Titan Embeddings v2
- OpenSearch Serverless backend
- Automatic schema updates

## Cleanup

To delete all resources:

```bash
bash destroy.sh
```

This removes:
- CloudFormation stack
- S3 buckets and data
- Bedrock agent and memory
- ECR repositories
- IAM roles and policies
- Glue databases
- Local artifacts

## Troubleshooting

### Agent Not Responding
- Check Lambda logs: `aws logs tail /aws/lambda/ChatAppWebSocketLambda --follow`
- Verify agent ARN in Lambda environment variables
- Ensure Bedrock model access is enabled

### Memory Not Working
- Confirm session ID format: `spa-persistent-{user_id}`
- Check memory ID in deployment JSON file
- Verify IAM permissions for `bedrock-agentcore:GetMemory`

### WebSocket Disconnects
- Heartbeat sends ping every 25 seconds
- API Gateway timeout is 10 minutes
- Refresh browser if idle > 5 minutes

### Deployment Fails
- Ensure AWS CLI is configured: `aws sts get-caller-identity`
- Check region supports Bedrock AgentCore: `us-east-1`, `us-west-2`
- Verify Python 3.12+ and Node.js 18+ installed

## Project Structure

```
RFQAssistant/
├── src/                          # React frontend
│   ├── App.js                    # Main app component
│   ├── Chat.js                   # Chat interface with WebSocket
│   └── aws-config.js             # Generated AWS config
├── public/                       # Static assets
├── spa_multi_agent_system_v8.py  # Agent code (Strands)
├── deploy_spa_multi_agent_system_v8.py  # Agent deployment
├── infrastructure.yaml           # CloudFormation template
├── deploy.sh                     # Main deployment script
├── destroy.sh                    # Cleanup script
├── sample_data.zip               # SAP data
├── sample_comp_data.zip          # Compliance data
├── sample_kb_data.zip            # Knowledge base data
├── glue_catalog_export.zip       # Glue views
└── package.json                  # Node.js dependencies
```

## Technology Stack

- **Frontend**: React 18, AWS Amplify UI, WebSocket
- **Backend**: AWS Lambda (Python 3.12), API Gateway WebSocket
- **Agent**: Strands Agents SDK, Bedrock AgentCore Runtime
- **Tool Integration**: Model Context Protocol (MCP), Bedrock AgentCore Gateway
- **AI Models**: Claude 3.7 Sonnet, Titan Embeddings v2
- **Data**: Amazon Athena, AWS Glue, S3, DynamoDB
- **Auth**: Amazon Cognito (User Pool + Gateway Pool), JWT, OAuth2
- **Infrastructure**: CloudFormation, CloudFront, WAF

## Key Components

### Agent Tools
1. **lookup_schema**: Query Knowledge Base for table structures
2. **query_athena**: Execute SQL on SAP/compliance data
3. **get_financial_performance**: Vendor financial metrics
4. **get_supplier_quality_metrics**: Quality scores and ratings
5. **check_vendor_compliance**: REACH, ROHS, CMRT, RBA status
6. **validate_rfq_data**: Extract and validate RFQ fields
7. **execute_python**: Run Python code for visualizations
8. **create_rfq** (via MCP Gateway): Generate RFQ in SAP or demo mode through Lambda function

### Memory System
- **SPAMemoryHook**: Custom hook for context management
- **Context Extraction**: Regex-based vendor/material detection
- **Session Isolation**: Per-user conversation history
- **Automatic Storage**: Messages saved on each turn

## Performance

- **Agent Response**: 2-5 seconds (streaming)
- **WebSocket Latency**: <100ms
- **CloudFront Cache**: 24 hours for static assets
- **Athena Queries**: 1-3 seconds typical
- **Memory Retrieval**: <500ms

## Security Best Practices

✅ All S3 buckets are private (OAC only)  
✅ WAF rate limiting (2000 req/5min per IP)  
✅ Cognito JWT validation on WebSocket  
✅ IAM least-privilege policies  
✅ Secrets Manager for credentials  
✅ VPC endpoints for private connectivity (optional)  
✅ CloudWatch logging enabled  

## Cost Estimate

Typical monthly costs (low usage, ~100 conversations/month):

### Compute & Runtime
- **Bedrock AgentCore Runtime**: $50-100
  - Agent runtime hours: ~$0.10/hour
  - Estimated 500-1000 hours/month for always-on agent
- **Lambda (WebSocket Handler)**: $5-10
  - Invocations + duration charges
- **ECS/Fargate (AgentCore Container)**: Included in AgentCore pricing

### AI Models
- **Claude 3.7 Sonnet**: $30-80
  - Input: $3 per 1M tokens
  - Output: $15 per 1M tokens
  - ~10-20M tokens/month typical usage
- **Titan Embeddings v2**: $5-10
  - $0.0001 per 1K tokens
  - Knowledge Base queries

### Data & Storage
- **Athena**: $5-10 (query execution, $5 per TB scanned)
- **S3**: $5-10 (storage + requests)
- **DynamoDB**: $2-5 (WebSocket connections table)
- **Glue**: $5 (crawler runs + catalog storage)
- **OpenSearch Serverless**: $10-20 (Knowledge Base vector store)

### Networking & CDN
- **CloudFront**: $5-10 (data transfer + requests)
- **API Gateway WebSocket**: $3-5 (connections + messages)

### Other Services
- **Cognito**: Free tier (50,000 MAUs)
- **Secrets Manager**: $0.40 (1 secret)
- **CloudWatch Logs**: $2-5 (log ingestion + storage)

### SDK & Framework
- **Strands Agents SDK**: **FREE** (open-source)
- **Bedrock AgentCore Starter Toolkit**: **FREE** (AWS provided)

---

**Total Estimated Cost**: ~$150-300/month for development/testing

**Production Cost** (1000+ conversations/month): ~$500-1000/month

**Cost Optimization Tips**:
- Use Claude 3.5 Haiku instead of Sonnet for 90% cost reduction on model calls
- Implement caching for frequently accessed data
- Set up S3 lifecycle policies for old data
- Use reserved capacity for predictable workloads
- Monitor CloudWatch metrics to identify cost drivers

## Support

For issues or questions:
- Check CloudWatch Logs for agent/Lambda errors
- Review deployment logs in terminal
- Verify AWS service quotas and limits
- Ensure all prerequisites are met

## License

This project is provided as-is for **demonstration and educational purposes only**. 

**This code is NOT production-ready and should NOT be deployed to production environments without:**
- Comprehensive security review and testing
- Implementation of additional security controls
- Compliance validation with your organization's policies
- Proper error handling and monitoring
- Performance optimization and load testing
- Data privacy and regulatory compliance verification

Use at your own risk. The authors and contributors are not responsible for any issues arising from the use of this code in production environments.

## Acknowledgments

Built with:
- [Strands Agents SDK](https://github.com/awslabs/strands-agents) - Agent framework
- [Amazon Bedrock](https://aws.amazon.com/bedrock/) - Foundation models
- [AWS Amplify](https://aws.amazon.com/amplify/) - Frontend framework
