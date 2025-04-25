import asyncio
import json
import os
import re
from typing import TYPE_CHECKING, Dict, List, Any, Optional

from loguru import logger

from embeddings_matcher import EmbeddingsMatcher
from models import ParsedReceipt
from openai.types.chat.chat_completion import ChatCompletion

if TYPE_CHECKING:
    from receipt_parser import ReceiptParser
    from agents import AgentsWorker

class Orchestrator:
    def __init__(
        self,
        receipt_parser: 'ReceiptParser',
        agents_worker: 'AgentsWorker',
    ):
        self.receipt_parser = receipt_parser
        self.agents_worker = agents_worker
        self.embeddings_matcher = EmbeddingsMatcher(
            redis_client=self.agents_worker.redis
        )
        self.client = receipt_parser.client
        self.together_client = receipt_parser.together_client
        self.receipt_parser.embeddings_matcher = self.embeddings_matcher
        self.receipt_parser.update_stage = self.agents_worker.update_stage
        self.agents_worker.compare_duplicate_receipts = self.receipt_parser.compare_duplicate_receipts
        
        # Load ruleset
        with open("ruleset.json", "r") as file:
            self.ruleset : dict = json.load(file)
        
        # Define available tools/agents
        self.available_tools = {
            "get_employee_data": self.agents_worker.get_employee_data,
            "update_expense_budget": self.agents_worker.update_expense_budget,
            "check_location_proximity": self.agents_worker.check_location_proximity,
            "is_duplicate_receipt": self.agents_worker.is_duplicate_receipt,
            "send_email": self.agents_worker.send_email
        }

    async def orchestrate(
        self,
        img_base64: str,
        file_id: str,
        employee_id: Optional[str] = None
    ):
        # Parse the receipt
        parsed_results: ParsedReceipt = await self.receipt_parser.parse_receipt_from_base64(
            file_id=file_id,
            employee_id=employee_id,
            img_base64=img_base64
        )

        # Save the receipt with embeddings
        await asyncio.create_task(
            asyncio.to_thread(
                self.embeddings_matcher.save_receipt,
                receipt_type=parsed_results.receipt_type, 
                file_id=file_id,
                image_base64=img_base64,
                receipt_content=parsed_results.receipt_content
            )
        )
        logger.success(f"Receipt {file_id} saved with embeddings.")
        self.agents_worker.update_stage(
            file_id=file_id,
            stage=4,
            details={
                "file_id" : file_id,
                "employee_id" : employee_id,
                "stage_name" : "Text Embeddings on Extracted OCR Content"
            }
        )
        
        # Get the relevant business rules based on receipt type
        applicable_rule = self.ruleset.get(parsed_results.receipt_type, "No specific rules apply.")
        
        # Prepare context and conversation history
        context = {
            "receipt_type": parsed_results.receipt_type,
            "receipt_content": parsed_results.receipt_content,
            "applicable_rule": applicable_rule,
            "employee_id": employee_id,
            "file_id": file_id,
            "conversation": []
        }
        
        # Start the agent loop
        all_context_data =  await self._agent_loop(
            context, 
            origin_image_base_64=img_base64, 
            possible_duplicate_data=parsed_results.possible_duplicate_data,
        )
        logger.success(f"Orchestration completed for receipt {file_id}.")
        return True
    
    async def _execute_tool(
        self, 
        file_id,
        employee_id,
        max_iterations,
        tool_name: str, 
        parameters: Dict[str, Any],
        origin_image_base_64: str,
        possible_duplicate_data: Optional[Dict[str, Any]] = None,
    ):
        """
        Execute a tool with the given parameters.
        
        Args:
            tool_name: The name of the tool to execute
            parameters: The parameters to pass to the tool
            
        Returns:
            The result of the tool execution
        """
        try:
            tool_func = self.available_tools.get(tool_name)
            if not tool_func:
                return {"error": f"Tool {tool_name} not found"}
            
            # Remove final_tool_call from parameters before passing to the tool
            exec_params = {k: v for k, v in parameters.items() if k != "final_tool_call"}
            
            # Add common parameter to all function calls, possible_duplicate_data
            if possible_duplicate_data:
                exec_params["origin_image_base_64"] = origin_image_base_64
                exec_params["possible_duplicate_data"] = possible_duplicate_data

            exec_params["file_id"] = file_id
            exec_params["employee_id"] = employee_id
            exec_params["max_iterations"] = max_iterations
            
            if asyncio.iscoroutinefunction(tool_func):
                result = await tool_func(**exec_params)
            else:
                result = tool_func(**exec_params)
            
            return result
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return {"error": f"Error executing tool {tool_name}: {str(e)}"}
        

    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        Parse the LLM's response to extract either tool calls or reasoning.
        
        Args:
            response: The LLM's response text
            
        Returns:
            A dictionary with the parsed response type and content
        """
        try:
            # First, check if this contains multiple tool calls (which we need to prevent)
            tool_tags = re.findall(r"<tool>.*?</tool>", response, re.DOTALL)
            if len(tool_tags) > 1:
                # Extract just the first tool call to avoid multiple executions
                logger.warning(f"Multiple tool calls detected. Processing only the first one.")
                first_tool_start = response.find("<tool>")
                next_tool_start = response.find("<tool>", first_tool_start + 1)
                
                if next_tool_start > 0:
                    response = response[:next_tool_start]
                    logger.warning(f"Truncated response to first tool call only")
            
            # Check for reasoning-only response
            if "<tool>" not in response and "<reasoning>" in response:
                reasoning_match = re.search(r"<reasoning>(.*?)</reasoning>", response, re.DOTALL)
                if reasoning_match:
                    reasoning_content = reasoning_match.group(1).strip()
                    return {
                        "type": "reasoning",
                        "reasoning": reasoning_content
                    }
            
            # Extract tool name
            tool_match = re.search(r"<tool>(.*?)</tool>", response, re.DOTALL)
            if not tool_match:
                return {"type": "error", "message": "No tool specified in the response"}
            
            tool_name = tool_match.group(1).strip()
            
            # Extract parameters
            params_match = re.search(r"<parameters>(.*?)</parameters>", response, re.DOTALL)
            parameters = {}
            
            if params_match:
                params_json = params_match.group(1).strip()
                try:
                    parameters = json.loads(params_json)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in parameters: {params_json}")
                    return {"type": "error", "message": "Invalid JSON in parameters"}
            
            # Extract final_tool_call flag - default to true for send_email to break loops
            final_tool_call = False
            final_match = re.search(r"<final_tool_call>(.*?)</final_tool_call>", response, re.DOTALL)
            
            if final_match:
                final_str = final_match.group(1).strip().lower()
                final_tool_call = final_str in ["true", "yes", "1"]
            
            # Force final_tool_call to true for send_email to prevent infinite loops
            if tool_name == "send_email":
                final_tool_call = True
                logger.info("Setting final_tool_call to true for send_email")
            
            # Extract reasoning if present
            reasoning_match = re.search(r"<reasoning>(.*?)</reasoning>", response, re.DOTALL)
            reasoning = reasoning_match.group(1).strip() if reasoning_match else ""
            
            return {
                "type": "tool_call",
                "tool": tool_name,
                "parameters": parameters,
                "final_tool_call": final_tool_call,
                "reasoning": reasoning
            }
            
        except Exception as e:
            logger.error(f"Error parsing response: {e}")
            return {"type": "error", "message": f"Error parsing response: {str(e)}"}

    async def _agent_loop(
            self, 
            context: Dict[str, Any],
            origin_image_base_64: str,
            possible_duplicate_data: Optional[Dict[str, Any]] = None,
            max_iterations: int = 10  # Add a safety limit
    ) -> Dict[str, Any]:
        """
        Execute the LLM-based agent loop to process the receipt.
        
        Args:
            context: The context containing conversation history and receipt information
            origin_image_base_64: Base64 encoded image of the receipt
            possible_duplicate_data: Optional data about potential duplicates
            max_iterations: Maximum number of iterations to prevent infinite loops
            
        Returns:
            The final result of the orchestration
        """
        is_final_call = False
        iteration_count = 0
        file_id = context.get("file_id")
        employee_id = context.get("employee_id")

        # Generate the system prompt with relevant rules and context
        system_prompt = self._generate_system_prompt(context, possible_duplicate_data)

        self.agents_worker.update_stage(
            file_id=file_id,
            stage=5,
            details={
                "file_id" : file_id,
                "employee_id" : employee_id,
                "system_prompt" : system_prompt,
                "stage_name" : "Preparing System Prompt for Orchestrator"
            }
        )
        
        # Initialize conversation if empty
        if not context.get("conversation"):
            employee_id = context.get("employee_id", "Unknown")
            receipt_type = context.get("receipt_type")
            
            initial_user_prompt = f"""Process this {receipt_type} receipt for employee ID: {employee_id}.

    Start by making ONE tool call at a time to gather information and complete the workflow.
    {f"""
IMPORTANT: There are high chances of this receipt/invoice being a duplicate, perform a duplicate to confirm.""" if possible_duplicate_data else ""}
    """

            # Add the initial user prompt to the conversation history only
            context["conversation"] = [
                {"role": "user", "content": initial_user_prompt}
            ]
        
        while not is_final_call and iteration_count < max_iterations:
            iteration_count += 1
            logger.info(f"Agent loop iteration: {iteration_count}/{max_iterations}")
            
            # Prepare messages for each request - system prompt followed by conversation
            messages = [
                {"role": "system", "content": system_prompt},
            ]
            
            # Add existing conversation history
            for msg in context.get("conversation", []):
                messages.append(msg)
            
            # Call the LLM
            response: ChatCompletion = await asyncio.create_task(asyncio.to_thread(
                self.together_client.chat.completions.create,
                model="Qwen/Qwen2.5-7B-Instruct-Turbo",
                # self.client.chat.completions.create,
                # model="action",
                temperature=0.3,
                seed=42,
                max_tokens=400,
                messages=messages
            ))
            
            # Extract the model's response
            agent_response = response.choices[0].message.content
            logger.warning(f"Agent Response: {agent_response}")
            
            # Parse the agent's response
            parsed_response = self._parse_response(agent_response)
            
            # Add the agent's response to the conversation
            context["conversation"].append({"role": "assistant", "content": agent_response})
            
            # Handle different response types
            if parsed_response.get("type") == "error":
                logger.error(f"Error in agent response: {parsed_response.get('message')}")
                error_message = f"""<response_error>
    Please provide a single, valid tool call or reasoning. Format: 
    <reasoning>Your detailed reasoning</reasoning>
    <tool>tool_name</tool>
    <parameters>{{...}}</parameters>
    <final_tool_call>true/false</final_tool_call>
    </response_error>"""
                context["conversation"].append({"role": "user", "content": error_message})
                continue
                
            elif parsed_response.get("type") == "reasoning":
                # This is a validation-only step, add validation result to the conversation
                validation_result = f"""<validation_result>
    Validation processed. Continue to the next step.
    </validation_result>"""
                context["conversation"].append({"role": "user", "content": validation_result})
                continue
                
            elif parsed_response.get("type") == "tool_call":
                # Handle tool call
                tool_name = parsed_response.get("tool")
                tool_params = parsed_response.get("parameters", {})
                is_final_call = parsed_response.get("final_tool_call", False)
                
                if tool_name in self.available_tools:
                    # Add the final_tool_call parameter to the tool parameters
                    tool_params["final_tool_call"] = is_final_call
                    
                    # Execute the tool
                    tool_result = await self._execute_tool(
                        file_id,
                        employee_id,
                        max_iterations,
                        tool_name, 
                        tool_params, 
                        origin_image_base_64, 
                        possible_duplicate_data,
                    )
                    
                    # Add the tool result to the conversation
                    tool_result_message = f"""<tool_result>
    <tool>{tool_name}</tool>
    <result>{json.dumps(tool_result, indent=2)}</result>
    </tool_result>"""
                    context["conversation"].append({"role": "user", "content": tool_result_message})
                    
                    # Special handling for send_email to prevent loops
                    if tool_name == "send_email":
                        logger.info("Email sent. Ending agent loop.")
                        is_final_call = True
                        
                    # If this was marked as the final tool call, return
                    if is_final_call:
                        print(f"\n{messages}\n")
                        return {
                            "status": "completed", 
                            "message": f"Process completed with final tool: {tool_name}",
                            "context": context
                        }
                else:
                    # Tool not found
                    error_message = f"""<tool_error>
    Tool '{tool_name}' not found. Available tools: {', '.join(self.available_tools.keys())}
    </tool_error>"""
                    context["conversation"].append({"role": "user", "content": error_message})
            
        # If we reached max iterations, return with a timeout status
        if iteration_count >= max_iterations:
            logger.warning(f"Agent loop reached maximum iterations ({max_iterations})")
            return {
                "status": "timeout",
                "message": f"Process timed out after {max_iterations} iterations",
                "context": context
            }
        
        return {"status": "completed", "context": context}

    def _generate_system_prompt(
        self, 
        context: Dict[str, Any],
        possible_duplicate_data
    ) -> str:
        """Generate the system prompt for the LLM."""
        receipt_type = context.get("receipt_type")
        applicable_rule = context.get("applicable_rule", "No specific rules apply.")
        
        return f"""You are an AI assistant that helps process receipts for expense reimbursement based on business rules.

###RECEIPT INFORMATION:
Type: {receipt_type}
Content: {context.get('receipt_content')}

###APPLICABLE BUSINESS RULES:
{applicable_rule}

###YOUR TASK:
Analyze the receipt information and determine what actions need to be taken. You have access to the following tools:

1. get_employee_data -> Gives back employee name, email id, employee level and current expenses
Parameters: {{ "employee_id": "EMPLOYEE_ID" }}

2. update_expense_budget -> Gives back success message when expense is updated
Parameters: {{ "employee_id": "EMPLOYEE_ID", "expense_type": "TYPE", "amount": VALUE, "increment": BOOLEAN }}

3. check_location_proximity -> Gives back true or false 
Parameters: {{ "src_address": "SOURCE_ADDRESS", "dest_address": "DESTINATION_ADDRESS" }}

4. send_email -> Gives back success message when email is sent
Parameters: {{ "email_id": "EMPLOYEE_EMAIL_ADDRESS", "subject": "EMAIL_SUBJECT", "content": "EMAIL_CONTENT" }}
{f"""
5. is_duplicate_receipt -> Gives back if receipt is a duplicate or not and justication
Parameters: {{ "employee_id": "EMPLOYEE_ID" }}
""" if possible_duplicate_data else ""}

###STRICT RESPONSE FORMAT:
<reasoning>Your reasoning about what to do next, also consider if this will be final tool call</reasoning>
<tool>tool_name</tool>
<parameters>
{{
    "param1": "value1",
    "param2": "value2"
}}
</parameters>
<final_tool_call>true_or_false</final_tool_call>

###IMPORTANT RULES:
- **ALWAYS generate ONLY one tool call at a time**
- **ALWAYS check all business rules**
- **set <final_tool_call> to true only when you are done with all operations and want to end the process.**
- **If for validation purpose, a tool is NOT available, perform it inside the reasoning and then continue with the next step**
- NEVER fabricate your own rules, ONLY refer to applicable business rules
- Only send email as the final step of the process
- Email content should have greeting with name, body and finally outro saying "From HR Bot" with all three sections separated by newlines
{f"""
- If a duplicate receipt is confirmed, get employee data and send email to employee with justification
""" if possible_duplicate_data else ""}
"""