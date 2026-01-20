from strands import Agent, tool
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from bedrock_agentcore.tools.code_interpreter_client import code_session
import boto3
import time
import json
import requests
import re
import os
import logging
import traceback
import uuid
import base64
from datetime import datetime, timedelta
from botocore.exceptions import ClientError

# Initialize Bedrock Agent Core App
app = BedrockAgentCoreApp()

# Dynamic Configuration
AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
MODEL_ID = os.getenv('MODEL_ID', 'us.anthropic.claude-sonnet-4-20250514-v1:0')
NOVA_MODEL_ID = os.getenv('NOVA_MODEL_ID', 'amazon.nova-micro-v1:0')
S3_OUTPUT = os.getenv('S3_OUTPUT_BUCKET')  # No default - must be provided by deployment
ATHENA_DB = os.getenv('ATHENA_DATABASE', 'sapdatadb')
COMPLIANCE_DB = os.getenv('COMPLIANCE_DATABASE', 'compdatadb')
KNOWLEDGE_BASE_ID = os.getenv('KNOWLEDGE_BASE_ID')
SAP_URL = os.getenv('SAP_URL')
SECRET_NAME = os.getenv('SECRET_NAME')
MEMORY_EXPIRY_DAYS = int(os.getenv('MEMORY_EXPIRY_DAYS', '30'))
MEMORY_CONTEXT_TURNS = int(os.getenv('MEMORY_CONTEXT_TURNS', '10'))
SPA_MEMORY_ID = os.getenv('SPA_MEMORY_ID')
SPA_MEMORY_NAME = os.getenv('SPA_MEMORY_NAME')
CODE_INTERPRETER_BUCKET = os.getenv('CODE_INTERPRETER_BUCKET', 'spa-code-interpreter-output')

# Gateway Configuration - MCP Client with OAuth2
GATEWAY_URL = os.getenv('GATEWAY_URL')
GATEWAY_COGNITO_CLIENT_ID = os.getenv('GATEWAY_COGNITO_CLIENT_ID')
GATEWAY_COGNITO_CLIENT_SECRET = os.getenv('GATEWAY_COGNITO_CLIENT_SECRET')
GATEWAY_TOKEN_URL = os.getenv('GATEWAY_TOKEN_URL')

# Global MCP client and tools cache
_mcp_client = None
_mcp_tools_cache = None
_access_token_cache = None
_token_expiry = None

# Setup logging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("spa-multi-agent")

# Initialize AWS clients
try:
    athena = boto3.client("athena", region_name=AWS_REGION)
    bedrock_kb = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    if SAP_URL and SECRET_NAME:
        secretsmanager = boto3.client('secretsmanager', region_name=AWS_REGION)
    logger.info("AWS clients initialized successfully")
except Exception as e:
    logger.warning(f"Failed to initialize AWS clients: {e}")
    raise

# Memory setup with error handling
client = None
memory_id = None

# Get memory details from deployment script
DEPLOYED_MEMORY_ID = SPA_MEMORY_ID
DEPLOYED_MEMORY_NAME = SPA_MEMORY_NAME

# ADD THIS DEBUG LOGGING:
logger.info("🔍 MEMORY SETUP DEBUG:")
logger.info(f"   SPA_MEMORY_ID env var: '{DEPLOYED_MEMORY_ID}'")
logger.info(f"   SPA_MEMORY_NAME env var: '{DEPLOYED_MEMORY_NAME}'")
logger.info(f"   AWS_REGION: '{AWS_REGION}'")

try:
    logger.info("Setting up SPA Multi-Agent Memory...")
    client = MemoryClient(region_name=AWS_REGION)
    
    # Strategy 1: Use deployed memory ID (most reliable)
    if DEPLOYED_MEMORY_ID:
        try:
            logger.info(f"Using deployed memory ID: {DEPLOYED_MEMORY_ID}")
            # Verify memory exists and is accessible
            memory_details = client.get_memory(memoryId=DEPLOYED_MEMORY_ID)
            memory_id = DEPLOYED_MEMORY_ID
            logger.info(f"✅ Deployed memory verified - Name: {memory_details.get('name', 'Unknown')}")
        except Exception as e:
            logger.warning(f"Deployed memory ID {DEPLOYED_MEMORY_ID} not accessible: {e}")
            memory_id = None
    
    # Strategy 2: Search by deployed memory name (fallback)
    if not memory_id and DEPLOYED_MEMORY_NAME:
        try:
            logger.info(f"Searching for deployed memory name: {DEPLOYED_MEMORY_NAME}")
            memories = client.list_memories()
            
            for memory in memories:
                if memory.get('name') == DEPLOYED_MEMORY_NAME:
                    memory_id = memory.get('id')
                    logger.info(f"✅ Found memory by name: {DEPLOYED_MEMORY_NAME}, ID: {memory_id}")
                    break
            
            if not memory_id:
                logger.warning(f"Memory with name '{DEPLOYED_MEMORY_NAME}' not found")
        except Exception as e:
            logger.warning(f"Memory search by name failed: {e}")
    
except Exception as e:
    logger.error(f"Memory initialization failed: {e}")
    logger.error(f"Error details: {traceback.format_exc()}")
    client = None
    memory_id = None

# Log final memory status
if memory_id:
    logger.info(f"🎯 Memory ready - ID: {memory_id}")
else:
    logger.warning("⚠️ Memory setup failed - agent will run without memory")

# Utility Functions
def check_query_status(execution_id):
    response = athena.get_query_execution(QueryExecutionId=execution_id)
    return response['QueryExecution']['Status']['State']

def get_query_results(execution_id):
    max_wait = 30
    wait_count = 0
    
    while wait_count < max_wait:
        status = check_query_status(execution_id)
        if status in ['SUCCEEDED', 'FAILED', 'CANCELLED']:
            break
        time.sleep(1)
        wait_count += 1

    if status == 'SUCCEEDED':
        return athena.get_query_results(QueryExecutionId=execution_id)
    else:
        error_details = athena.get_query_execution(QueryExecutionId=execution_id)
        state_change_reason = error_details['QueryExecution']['Status'].get('StateChangeReason', 'Unknown error')
        return {"error": f"Query failed: {state_change_reason}"}

def get_sap_credentials():
    if not SAP_URL or not SECRET_NAME:
        return None, None
    try:
        response = secretsmanager.get_secret_value(SecretId=SECRET_NAME)
        secret = json.loads(response['SecretString'])
        return secret.get('SAPUSER'), secret.get('SAPPASSWORD')
    except Exception as e:
        logger.error(f"Error retrieving SAP credentials: {e}")
        return None, None

def get_gateway_access_token():
    """Get access token from Gateway Cognito using OAuth2 client credentials with caching"""
    global _access_token_cache, _token_expiry
    
    if _access_token_cache and _token_expiry and time.time() < _token_expiry:
        return _access_token_cache
    
    try:
        if not GATEWAY_TOKEN_URL or not GATEWAY_COGNITO_CLIENT_ID or not GATEWAY_COGNITO_CLIENT_SECRET:
            logger.error("Gateway OAuth2 credentials not configured")
            return None
        
        response = requests.post(
            GATEWAY_TOKEN_URL,
            data=f"grant_type=client_credentials&client_id={GATEWAY_COGNITO_CLIENT_ID}&client_secret={GATEWAY_COGNITO_CLIENT_SECRET}",
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        response.raise_for_status()
        token_data = response.json()
        _access_token_cache = token_data['access_token']
        _token_expiry = time.time() + (50 * 60)
        return _access_token_cache
    except Exception as e:
        logger.error(f"Failed to get Gateway access token: {e}")
        return None

def create_streamable_http_transport(mcp_url: str, access_token: str):
    """Create HTTP transport for MCP client with Bearer token"""
    return streamablehttp_client(mcp_url, headers={"Authorization": f"Bearer {access_token}"})

def get_mcp_tools():
    """Get tools from Gateway MCP server - called once at startup"""
    global _mcp_tools_cache, _mcp_client
    
    if _mcp_tools_cache is not None:
        return _mcp_tools_cache
    
    try:
        if not GATEWAY_URL:
            logger.warning("Gateway URL not configured - MCP tools unavailable")
            return []
        
        access_token = get_gateway_access_token()
        if not access_token:
            logger.warning("Failed to get access token - MCP tools unavailable")
            return []
        
        _mcp_client = MCPClient(lambda: create_streamable_http_transport(GATEWAY_URL, access_token))
        _mcp_client.__enter__()
        
        tools = []
        pagination_token = None
        while True:
            tmp_tools = _mcp_client.list_tools_sync(pagination_token=pagination_token)
            tools.extend(tmp_tools)
            if tmp_tools.pagination_token is None:
                break
            pagination_token = tmp_tools.pagination_token
        
        _mcp_tools_cache = tools
        logger.info(f"✅ Loaded {len(tools)} MCP tools from Gateway: {[t.tool_name for t in tools]}")
        return tools
    except Exception as e:
        logger.error(f"Failed to get MCP tools: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return []


@tool
def lookup_schema(question: str) -> str:
    """Ask Bedrock Knowledge Base about available tables/columns."""
    try:
        response = bedrock_kb.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={"text": question},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 3}}
        )
        docs = response.get("retrievalResults", [])
        if not docs:
            return "No schema information found for your query."
        return "\n".join([d["content"]["text"] for d in docs])
    except Exception as e:
        logger.error(f"Schema lookup error: {e}")
        return f"Error accessing schema information: {str(e)}"

def _extract_rfq_data_from_context(user_input: str, conversation_context: str = "") -> dict:
    """Extract RFQ data from user input and conversation context including RFQ Name."""
    try:
        # Combine current input with context for extraction
        full_text = f"{conversation_context}\n{user_input}"
        
        # Enhanced patterns to catch various formats
        material_patterns = [
            r'material\s+(?:number\s*)?:?\s*([A-Z0-9\-]+)',
            r'for\s+material\s+([A-Z0-9\-]+)',
            r'mat\s*:?\s*([A-Z0-9\-]+)',
            r'\b([A-Z]{2,4}-[A-Z]{2,4}-[A-Z0-9]{3,6}-[0-9]{2})\b'
        ]
        
        supplier_patterns = [
            r'supplier\s+(?:id\s*)?:?\s*([A-Z0-9\-]+)',
            r'vendor\s+(?:id\s*)?:?\s*([A-Z0-9\-]+)',
            r'to\s+vendor\s+([A-Z0-9\-]+)',
            r'from\s+supplier\s+([A-Z0-9\-]+)',
            r'\b([A-Z]{3,5}-[A-Z0-9]{3,8})\b'
        ]
        
        quantity_patterns = [
            r'quantity\s*:?\s*([0-9]+)',
            r'qty\s*:?\s*([0-9]+)',
            r'for\s+quantity\s+([0-9]+)',
            r'amount\s*:?\s*([0-9]+)',
            r'\b([0-9]{1,6})\s+(?:units?|pieces?|pcs?)',
            r'(?:qty|quantity)\s+([0-9]+)'
        ]
        
        delivery_patterns = [
            r'delivery\s+date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})',
            r'delivery\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})',
            r'date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})',
            r'by\s+([0-9]{4}-[0-9]{2}-[0-9]{2})',
            r'on\s+([0-9]{4}-[0-9]{2}-[0-9]{2})'
        ]
        
        rfq_name_patterns = [
            r'rfq\s+name\s*:?\s*["\']?([^"\';\n]+)["\']?',
            r'name\s*:?\s*["\']?([^"\';\n]+)["\']?',
            r'rfq\s+title\s*:?\s*["\']?([^"\';\n]+)["\']?',
            r'title\s*:?\s*["\']?([^"\';\n]+)["\']?',
            r'call\s+(?:it|this)\s*:?\s*["\']?([^"\';\n]+)["\']?',
            r'named?\s*:?\s*["\']?([^"\';\n]+)["\']?'
        ]
        
        # Extract data
        material_number = None
        for pattern in material_patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                material_number = matches[-1]
                break
        
        supplier_id = None
        for pattern in supplier_patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                supplier_id = matches[-1]
                break
                
        quantity = None
        for pattern in quantity_patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                quantity = matches[-1]
                break
                
        delivery_date = None
        for pattern in delivery_patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                delivery_date = matches[-1]
                break
        
        rfq_name = None
        for pattern in rfq_name_patterns:
            matches = re.findall(pattern, full_text, re.IGNORECASE)
            if matches:
                rfq_name = matches[-1].strip()
                break
        
        return {
            "material_number": material_number,
            "supplier_id": supplier_id,
            "quantity": quantity,
            "delivery_date": delivery_date,
            "rfq_name": rfq_name
        }
        
    except Exception as e:
        logger.error(f"Error extracting RFQ data: {e}")
        return {
            "material_number": None, 
            "supplier_id": None, 
            "quantity": None, 
            "delivery_date": None,
            "rfq_name": None
        }

@tool
def query_athena(query: str) -> str:
    """Run SQL query in Athena and return results."""
    try:
        response = athena.start_query_execution(
            QueryString=query,
            QueryExecutionContext={"Database": ATHENA_DB},
            ResultConfiguration={'OutputLocation': S3_OUTPUT}
        )
        execution_id = response['QueryExecutionId']
        result = get_query_results(execution_id)

        if isinstance(result, dict) and 'error' in result:
            return result['error']

        rows = result.get("ResultSet", {}).get("Rows", [])
        if not rows:
            return "No results found for your query."

        output = []
        for row in rows:
            formatted_row = []
            for col in row.get("Data", []):
                value = ""
                for data_type, data_value in col.items():
                    if data_value:
                        value = str(data_value)
                        break
                formatted_row.append(value)
            output.append("\t".join(formatted_row))

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Query execution error: {e}")
        return f"Error executing query: {str(e)}"

@tool
def get_financial_performance(material_number: str) -> str:
    """Get financial performance data for vendors of a specific material."""
    try:
        query_sql = f"""
        SELECT 
            vendor_number, material_number, material_description,
            total_orders, total_invoices, avg_po_price, financial_score
        FROM v_spa_financial_performance 
        WHERE material_number = '{material_number}'
        ORDER BY financial_score DESC
        """
        result = query_athena(query_sql)
        if "No results found" in result:
            return f"No financial performance data found for material {material_number}."
        return result
    except Exception as e:
        logger.error(f"Financial performance error: {e}")
        return f"Error retrieving financial performance data: {str(e)}"

@tool
def get_supplier_quality_metrics(material_number: str) -> str:
    """Get quality metrics for suppliers of a specific material."""
    try:
        query_sql = f"""
        SELECT 
             vendor_number, total_orders, goods_receipt_rate, 
             non_return_rate, overall_quality_score 
        FROM v_spa_item_supplier_quality
        WHERE material_number = '{material_number}'
        ORDER BY overall_quality_score DESC
        """
        result = query_athena(query_sql)
        if "No results found" in result:
            return f"No quality metrics found for material {material_number}."
        return result
    except Exception as e:
        logger.error(f"Quality metrics error: {e}")
        return f"Error retrieving supplier quality metrics: {str(e)}"

@tool
def check_vendor_compliance(vendor_numbers: str) -> str:
    """FIXED: Check compliance status for vendor numbers - accepts ALL formats."""
    try:
        # Handle context references
        if vendor_numbers.lower() in ['context', 'previous', 'these', 'those', 'mentioned', 'these vendors', 'those suppliers']:
            return "I can see you're referring to previously mentioned vendors. Please provide the specific vendor numbers, or I can help if you tell me which material's vendors you want compliance data for."
        
        # Clean and parse vendor numbers - NO VALIDATION
        if vendor_numbers.startswith('[') and vendor_numbers.endswith(']'):
            vendor_numbers = vendor_numbers.replace('[', '').replace(']', '').replace('"', '').replace("'", "")
        
        vendor_list = [v.strip() for v in vendor_numbers.split(',') if v.strip()]
        
        if not vendor_list:
            return "Please provide vendor numbers to check compliance data."
        
        # NO FORMAT VALIDATION - Accept all vendor number formats
        # Pass directly to database and let it handle what exists
        vendor_conditions = "','".join(vendor_list)
        query_sql = f"""
        SELECT 
             vendor_number, "REACH Compliant", "ROHS Compliant", "CMRT", "RBA"
        FROM v_compliance_by_vendor
        WHERE vendor_number IN ('{vendor_conditions}')
        ORDER BY vendor_number
        """
        
        logger.info(f"Checking compliance for vendors: {vendor_list}")
        
        response = athena.start_query_execution(
            QueryString=query_sql,
            QueryExecutionContext={"Database": COMPLIANCE_DB},
            ResultConfiguration={'OutputLocation': S3_OUTPUT}
        )
        execution_id = response['QueryExecutionId']
        result = get_query_results(execution_id)

        if isinstance(result, dict) and 'error' in result:
            return f"Error querying compliance database: {result['error']}"

        rows = result.get("ResultSet", {}).get("Rows", [])
        if not rows or len(rows) <= 1:
            return f"No compliance data found for vendors: {', '.join(vendor_list)}. Please verify these vendor numbers exist in your compliance system."

        # Format results nicely
        output = []
        for row in rows:
            formatted_row = []
            for col in row.get("Data", []):
                value = ""
                for data_type, data_value in col.items():
                    if data_value:
                        value = str(data_value)
                        break
                formatted_row.append(value)
            output.append("\t".join(formatted_row))

        return "\n".join(output)

    except Exception as e:
        logger.error(f"Compliance check error: {e}")
        return f"Error retrieving compliance data: {str(e)}"

@tool
def validate_rfq_data(user_input: str) -> str:
    """Validate RFQ data extracted from user input."""
    try:
        material_match = re.search(r'material\s+number\s*:?\s*([A-Za-z0-9\-]+)', user_input, re.IGNORECASE)
        supplier_match = re.search(r'supplier\s+id\s*:?\s*([A-Za-z0-9\-]+)', user_input, re.IGNORECASE)
        quantity_match = re.search(r'quantity\s*:?\s*([0-9]+)', user_input, re.IGNORECASE)
        delivery_match = re.search(r'delivery\s+date\s*:?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})', user_input, re.IGNORECASE)
        
        extracted_data = {
            "material_number": material_match.group(1) if material_match else None,
            "supplier_id": supplier_match.group(1) if supplier_match else None,
            "quantity": quantity_match.group(1) if quantity_match else None,
            "delivery_date": delivery_match.group(1) if delivery_match else None,
        }
        
        missing_fields = []
        for field, value in extracted_data.items():
            if not value:
                missing_fields.append(field.replace('_', ' ').title())
        
        if missing_fields:
            return f"Missing required information: {', '.join(missing_fields)}"
        else:
            return f"RFQ data validated successfully: {json.dumps(extracted_data)}"
    
    except Exception as e:
        logger.error(f"RFQ validation error: {e}")
        return f"Error validating RFQ data: {str(e)}"

@tool
def execute_python(code: str) -> str:
    """Execute Python code in Code Interpreter. Code should upload charts to S3 and return the S3 URL."""
    try:
        # Generate pre-signed URL for upload (no IAM needed in sandbox)
        s3 = boto3.client('s3', region_name=AWS_REGION)
        chart_filename = f"chart_{uuid.uuid4().hex[:8]}.png"
        s3_key = f"visualizations/{chart_filename}"
        
        presigned_url = s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': CODE_INTERPRETER_BUCKET,
                'Key': s3_key,
                'ContentType': 'image/png'
            },
            ExpiresIn=300
        )
        
        # Inject S3 upload using presigned URL (no credentials needed)
        s3_upload_code = f'''
import requests
import os

# Upload chart to S3 using presigned URL
try:
    # Try both paths
    chart_path = '/tmp/chart.png' if os.path.exists('/tmp/chart.png') else 'chart.png'
    
    with open(chart_path, 'rb') as f:
        response = requests.put(
            '{presigned_url}',
            data=f.read(),
            headers={{'Content-Type': 'image/png'}}
        )
    
    if response.status_code == 200:
        print("[S3_SUCCESS]")
    else:
        print(f"[S3_ERROR]HTTP {{response.status_code}}[/S3_ERROR]")
except Exception as e:
    print(f"[S3_ERROR]{{str(e)}}[/S3_ERROR]")
'''
        
        # Ensure code saves chart (keep agent's original path or add /tmp/)
        if "plt.savefig" not in code:
            code = code.replace("plt.show()", "plt.savefig('chart.png', bbox_inches='tight', dpi=150)") if "plt.show()" in code else code + "\nplt.savefig('chart.png', bbox_inches='tight', dpi=150)\n"
        
        full_code = code + s3_upload_code
        
        # Execute code with S3 upload
        logger.info(f"📦 Executing code with S3 upload...")
        logger.info(f"🔗 Presigned URL generated for: {s3_key}")
        
        with code_session(AWS_REGION) as session:
            response = session.invoke("executeCode", {
                "code": full_code,
                "language": "python",
                "clearContext": False
            })
            
            result_text = ""
            upload_success = False
            
            for event in response["stream"]:
                logger.info(f"📦 Event: {json.dumps(event, default=str)[:500]}")
                if "result" in event:
                    result = event["result"]
                    logger.info(f"📦 Result type: {type(result)}")
                    logger.info(f"📦 Result content: {str(result)[:500]}")
                    
                    # Extract stdout from result - check both locations
                    if isinstance(result, dict):
                        # Try structuredContent first (new format)
                        if 'structuredContent' in result:
                            result_text = str(result['structuredContent'].get('stdout', '')) + str(result['structuredContent'].get('stderr', ''))
                        else:
                            # Fallback to direct stdout (old format)
                            result_text = str(result.get("stdout", "")) + str(result.get("stderr", ""))
                    else:
                        result_text = str(result)
                    
                    logger.info(f"📝 Result text: {result_text}")
                    
                    if "[S3_SUCCESS]" in result_text:
                        upload_success = True
                        logger.info(f"✅ Chart uploaded to: s3://{CODE_INTERPRETER_BUCKET}/{s3_key}")
                    
                    if "[S3_ERROR]" in result_text:
                        error = result_text.split("[S3_ERROR]")[1].split("[/S3_ERROR]")[0]
                        logger.error(f"❌ S3 upload error: {error}")
            
            if upload_success:
                s3_url = f"s3://{CODE_INTERPRETER_BUCKET}/{s3_key}"
                tool_output = f"[CODE_START]\n{code}\n[CODE_END]\n[EXEC_START]\nCode executed successfully\n[EXEC_END]\n[IMAGE]{s3_url}[/IMAGE]"
                logger.info(f"✅ Tool returning: {tool_output[:200]}...")
                return tool_output
            else:
                logger.error(f"❌ Upload failed. Full result: {result_text}")
                return f"Code executed but chart upload failed. Output: {result_text[:500]}"
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        logger.error(traceback.format_exc())
        return f"Error: {str(e)}"


# Load MCP tools at startup - AFTER all @tool functions are defined
mcp_tools = get_mcp_tools()
if mcp_tools:
    logger.info(f"🔧 MCP tools ready: {[t.tool_name for t in mcp_tools]}")
else:
    logger.warning("⚠️ No MCP tools loaded - Gateway features unavailable")



# Configure the model
model = BedrockModel(
    model_id=MODEL_ID,
    temperature=0.1
)

@app.entrypoint
async def spa_multi_agent_system(payload):
    """
    STREAMING: SPA Multi-Agent System with Bedrock AgentCore streaming support
    
    - Async generator that yields streaming events
    - Properly utilizes Bedrock AgentCore Memory for context
    - Streams agent responses in real-time
    """
    
    # CRITICAL: Instruction for agent to include [IMAGE] tags from tool output
    SYSTEM_PROMPT_PREFIX = """CRITICAL VISUALIZATION INSTRUCTION:
After calling execute_python tool, the tool will return text containing [IMAGE]s3://bucket/path[/IMAGE].
You MUST include this EXACT [IMAGE] tag in your response to the user.
Example:
- Tool returns: "[CODE_START]...code...[CODE_END][EXEC_START]Success[EXEC_END][IMAGE]s3://bucket/chart.png[/IMAGE]"
- Your response MUST include: "Here's the chart: [IMAGE]s3://bucket/chart.png[/IMAGE]"
DO NOT say "there was an issue with upload" - if tool returns [IMAGE] tag, the upload succeeded.
The [IMAGE] tag is how the frontend displays charts - it is REQUIRED.

"""
    
    try:
        # Validate payload
        if not payload or not isinstance(payload, dict):
            yield {"error": "Invalid request format"}
            return
        
        user_input = payload.get("prompt")
        if not user_input:
            yield {"error": "No prompt provided in request"}
            return

        user_id = payload.get("user_id", "default-user")
        session_id = f"spa-persistent-{user_id}"
        actor_id = f"spa-actor-{user_id}"
        
        logger.info(f"🎯 [STREAMING] Processing request in session: {session_id}")
        logger.info(f"📝 [STREAMING] User query: {user_input}")
        
        # Create session manager for context persistence
        session_manager = None
        if memory_id:
            try:
                memory_config = AgentCoreMemoryConfig(
                    memory_id=memory_id,
                    session_id=session_id,
                    actor_id=actor_id
                )
                session_manager = AgentCoreMemorySessionManager(
                    agentcore_memory_config=memory_config,
                    region_name=AWS_REGION
                )
                logger.info(f"✅ [STREAMING] SessionManager enabled for session: {session_id}")
            except Exception as e:
                logger.warning(f"⚠️ [STREAMING] SessionManager setup failed: {e}")
                session_manager = None
        else:
            logger.warning("⚠️ [STREAMING] Running without memory")
        
        # Create agent with MCP tools loaded at startup
        session_agent = Agent(
            session_manager=session_manager,
            model=model,
            tools=[
                lookup_schema, 
                query_athena, 
                get_financial_performance, 
                get_supplier_quality_metrics, 
                check_vendor_compliance, 
                validate_rfq_data,
                execute_python
            ] + mcp_tools,
            system_prompt=SYSTEM_PROMPT_PREFIX + """You are a comprehensive SPA (Supplier Performance Analysis) assistant with advanced context awareness.

CORE CAPABILITIES:
- RFQ creation with intelligent data extraction
- Financial performance analysis for suppliers
- Quality metrics evaluation
- Compliance status checking (REACH, ROHS, CMRT, RBA)
- Schema information lookup
- Data visualization with charts and graphs

CONTEXT AWARENESS:
You have access to the full conversation history. Use it to understand references to previously mentioned vendors, materials, and RFQ details. When users refer to "these vendors" or "that material", look back in the conversation to identify what they're referring to.

RFQ CREATION:
Use the create_rfq tool when users want to create an RFQ. The tool requires:
- material_number (required)
- supplier_id (required)  
- quantity (required)
- delivery_date (required, YYYY-MM-DD format)
- rfq_name (optional)

If the user provides all required fields, call the tool immediately. If fields are missing, the tool will indicate what's needed.

VISUALIZATIONS - CRITICAL:
ONLY use execute_python when user EXPLICITLY asks for charts, graphs, or visualizations.
Keywords that require visualization: "chart", "graph", "plot", "visualize", "visualization", "bar chart", "pie chart"
DO NOT use execute_python for simple data queries like "show", "get", "list", "display" data.

When user asks for charts/graphs:
1. Get data using appropriate tools
2. Generate Python code with matplotlib to create the chart
3. Call execute_python with your generated code
4. Code must save chart to: plt.savefig('chart.png', bbox_inches='tight', dpi=150)

TOOL SELECTION RULES:
- RFQ creation → use create_rfq tool directly (from MCP Gateway)
- Financial queries → use get_financial_performance()
- Quality queries → use get_supplier_quality_metrics()
- Compliance queries (show/get/list data) → use check_vendor_compliance() ONLY
- Schema questions → use lookup_schema()
- Custom analysis → use query_athena()
- Charts/graphs/visualizations ONLY → get data first, then use execute_python

RESPONSE STYLE:
- Extract context intelligently
- Never re-ask for information already provided
- Be concise and action-oriented
- Provide clear, structured responses
- For charts, provide S3 URL clearly""",
            state={"actor_id": actor_id, "session_id": session_id, "user_id": user_id}
        )
        
        # Stream the response using stream_async
        logger.info("🔄 [STREAMING] Starting agent stream...")
        
        async for event in session_agent.stream_async(user_input):
            # Yield each event from the agent stream
            yield event
            logger.debug(f"📤 [STREAMING] Event: {event.get('type', 'unknown')}")
        
        logger.info("✅ [STREAMING] Stream complete")
        
    except Exception as e:
        logger.error(f"[STREAMING] Error: {e}")
        logger.error(f"[STREAMING] Traceback: {traceback.format_exc()}")
        yield {"error": f"Error processing request: {str(e)}"}


async def spa_multi_agent_system_streaming(payload):
    """
    STREAMING VERSION: SPA Multi-Agent System with async streaming support
    
    Yields chunks as they are generated by the agent.
    Use this in async Lambda handler with WebSocket for real-time streaming.
    
    Yields:
        dict: Event with 'type' and 'data' fields
              - type='chunk': Text chunk from agent
              - type='tool': Tool execution info
              - type='complete': Final response
              - type='error': Error occurred
    """
    
    try:
        # Validate payload
        if not payload or not isinstance(payload, dict):
            yield {"type": "error", "data": "Error: Invalid request format."}
            return
        
        user_input = payload.get("prompt")
        if not user_input:
            yield {"type": "error", "data": "Error: No prompt provided in request."}
            return

        user_id = payload.get("user_id", "default-user")
        session_id = f"spa-persistent-{user_id}"
        actor_id = f"spa-actor-{user_id}"
        
        logger.info(f"🎯 [STREAMING] Processing request in session: {session_id}")
        logger.info(f"📝 [STREAMING] User query: {user_input}")
        
        # Create session manager for context persistence
        session_manager = None
        if memory_id:
            try:
                memory_config = AgentCoreMemoryConfig(
                    memory_id=memory_id,
                    session_id=session_id,
                    actor_id=actor_id
                )
                session_manager = AgentCoreMemorySessionManager(
                    agentcore_memory_config=memory_config,
                    region_name=AWS_REGION
                )
                logger.info(f"✅ [STREAMING] SessionManager enabled for session: {session_id}")
            except Exception as e:
                logger.warning(f"⚠️ [STREAMING] SessionManager setup failed: {e}")
                session_manager = None
        else:
            logger.warning("⚠️ [STREAMING] Running without memory")
        
        # Create agent with MCP tools loaded at startup
        session_agent = Agent(
            session_manager=session_manager,
            model=model,
            tools=[
                lookup_schema, 
                query_athena, 
                get_financial_performance, 
                get_supplier_quality_metrics, 
                check_vendor_compliance, 
                validate_rfq_data,
                execute_python
            ] + mcp_tools,
            system_prompt="""You are a comprehensive SPA (Supplier Performance Analysis) assistant with advanced context awareness.

CORE CAPABILITIES:
- RFQ creation with intelligent data extraction
- Financial performance analysis for suppliers
- Quality metrics evaluation
- Compliance status checking (REACH, ROHS, CMRT, RBA)
- Schema information lookup
- Data visualization with charts and graphs

CONTEXT AWARENESS:
You have access to the full conversation history. Use it to understand references to previously mentioned vendors, materials, and RFQ details. When users refer to "these vendors" or "that material", look back in the conversation to identify what they're referring to.

RFQ CREATION INSTRUCTIONS:
REQUIRED FIELDS:
- Material Number (e.g., MZ-RM-C900-06)
- Supplier ID (e.g., USSU-VSF01)
- Quantity (e.g., 10)
- Delivery Date (YYYY-MM-DD format, e.g., 2025-10-03)

OPTIONAL FIELDS:
- RFQ Name (e.g., "TSTRFQ", "Q4 Material Procurement")

When creating an RFQ:
1. Check the conversation history for any previously mentioned details
2. Extract all provided information from the current message
3. Ask for any missing required fields
4. Once you have all required data, call create_sap_rfq with a complete formatted string

VISUALIZATIONS - CRITICAL:
ONLY use execute_python when user EXPLICITLY asks for charts, graphs, or visualizations.
Keywords that require visualization: "chart", "graph", "plot", "visualize", "visualization", "bar chart", "pie chart"
DO NOT use execute_python for simple data queries like "show", "get", "list", "display" data.

When user asks for charts/graphs:
1. Get data using appropriate tools
2. Generate Python code with matplotlib to create the chart
3. Call execute_python with your generated code
4. Code must save chart to: plt.savefig('chart.png', bbox_inches='tight', dpi=150)

TOOL SELECTION RULES:
- RFQ creation → use create_sap_rfq(formatted_string_with_all_data)
- Financial queries → use get_financial_performance()
- Quality queries → use get_supplier_quality_metrics()
- Compliance queries (show/get/list data) → use check_vendor_compliance() ONLY
- Schema questions → use lookup_schema()
- Custom analysis → use query_athena()
- Charts/graphs/visualizations ONLY → get data first, then use execute_python

RESPONSE STYLE:
- Extract context intelligently
- Never re-ask for information already provided
- Be concise and action-oriented
- Provide clear, structured responses
- For charts, provide S3 URL clearly""",
            state={"actor_id": actor_id, "session_id": session_id, "user_id": user_id}
        )
        
        # Stream the response using stream_async
        logger.info("🔄 [STREAMING] Starting agent stream...")
        full_response = []
        
        async for event in session_agent.stream_async(user_input):
            # Handle different event types from Strands
            if "data" in event:
                # Text chunk from agent
                chunk = event["data"]
                full_response.append(chunk)
                yield {"type": "chunk", "data": chunk}
                logger.debug(f"📤 [STREAMING] Chunk: {chunk[:50]}...")
            
            elif "current_tool_use" in event:
                # Tool execution info
                tool_info = event["current_tool_use"]
                tool_name = tool_info.get("name", "unknown")
                logger.info(f"🔧 [STREAMING] Tool executing: {tool_name}")
                yield {"type": "tool", "data": {"tool_name": tool_name, "status": "executing"}}
            
            elif event.get("type") == "agent_turn_complete":
                # Agent finished processing
                logger.info("✅ [STREAMING] Agent turn complete")
        
        # Send completion event
        complete_response = "".join(full_response)
        logger.info(f"✅ [STREAMING] Stream complete. Total length: {len(complete_response)}")
        yield {"type": "complete", "data": complete_response}
        
    except Exception as e:
        logger.error(f"[STREAMING] Error: {e}")
        logger.error(f"[STREAMING] Traceback: {traceback.format_exc()}")
        yield {"type": "error", "data": f"Error processing request: {str(e)}"}

# Cleanup function
def cleanup_memory():
    """Clean up memory resources on shutdown"""
    global _mcp_client
    try:
        if _mcp_client:
            _mcp_client.__exit__(None, None, None)
            logger.info("MCP client closed")
        if memory_id and client:
            # Don't delete production memory - just log cleanup
            logger.info(f"Application shutting down - Memory {memory_id} remains available")
    except Exception as e:
        logger.warning(f"Memory cleanup warning: {e}")

import atexit
atexit.register(cleanup_memory)

# Application startup
if __name__ == "__main__":
    logger.info("🚀 SPA Multi-Agent System starting...")
    logger.info(f"📊 Configuration:")
    logger.info(f"   - AWS Region: {AWS_REGION}")
    logger.info(f"   - Model: {MODEL_ID}")
    logger.info(f"   - Memory enabled: {memory_id is not None}")
    if memory_id:
        logger.info(f"   - Memory ID: {memory_id}")
    logger.info(f"   - Knowledge Base: {KNOWLEDGE_BASE_ID}")
    logger.info(f"   - Athena Database: {ATHENA_DB}")
    logger.info(f"   - Compliance Database: {COMPLIANCE_DB}")
    logger.info("🎯 SPA Multi-Agent System ready for requests!")
    app.run()
