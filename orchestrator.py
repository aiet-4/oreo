import asyncio
import json
import os
import re
from typing import TYPE_CHECKING, Dict, List, Any, Optional

from loguru import logger

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
        self.client = receipt_parser.client  # Assuming the OpenAI client is in receipt_parser
        
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
            img_base64=img_base64
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
        return await self._agent_loop(context)
    
    async def _agent_loop(self, context: Dict[str, Any]):
        """
        Execute the LLM-based agent loop to process the receipt.
        
        Args:
            context: The context containing conversation history and receipt information
            
        Returns:
            The final result of the orchestration
        """
        is_final_call = False
        
        while not is_final_call:
            # Generate the system prompt with relevant rules and context
            system_prompt = self._generate_system_prompt(context)
            
            # Prepare messages for the LLM
            messages = [
                {"role": "system", "content": system_prompt},
            ]

            # Create initial user prompt if this is the first iteration (empty conversation)
            if not context.get("conversation"):
                employee_id = context.get("employee_id", "Unknown")
                receipt_type = context.get("receipt_type")
                
                initial_user_prompt = f"""Process this {receipt_type} receipt for employee ID: {employee_id}.

            Start by generating appropriate tool calls to gather necessary information, validate against policies, and complete the entire reimbursement workflow from verification to notification."""

                # Add the initial user prompt to both the messages and the conversation history
                messages.append({"role": "user", "content": initial_user_prompt})
                context["conversation"].append({"role": "user", "content": initial_user_prompt})
            else:
                # Add existing conversation history
                for msg in context.get("conversation", []):
                    messages.append(msg)
            
            # Call the LLM
            response: ChatCompletion = await asyncio.create_task(asyncio.to_thread(
                self.client.chat.completions.create,
                model="action",
                temperature=0.2,
                seed=1024,
                max_tokens=1024,
                messages=messages
            ))
            
            # Extract the model's response
            agent_response = response.choices[0].message.content

            logger.warning(f"Agent Response: {agent_response}")
            
            # Parse the agent's response to identify the tool and parameters
            tool_call = self._parse_tool_call(agent_response)
            
            # Add the agent's response to the conversation
            context["conversation"].append({"role": "assistant", "content": agent_response})
            
            # If no tool call is detected, we're done
            if not tool_call:
                return {"status": "completed", "message": "No further actions needed", "context": context}
            
            # Execute the tool call
            tool_name = tool_call.get("tool")
            tool_params = tool_call.get("parameters", {})
            is_final_call = tool_call.get("final_tool_call", False)
            
            if tool_name in self.available_tools:
                # Add the final_tool_call parameter to the tool parameters
                tool_params["final_tool_call"] = is_final_call
                
                tool_result = await self._execute_tool(tool_name, tool_params)
                
                # Add the tool result to the conversation
                tool_result_message = f"""<tool_result>
<tool>{tool_name}</tool>
<result>{json.dumps(tool_result, indent=2)}</result>
</tool_result>"""
                context["conversation"].append({"role": "user", "content": tool_result_message})
                
                # If this was marked as the final tool call, return
                if is_final_call:
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
        
        return {"status": "completed", "context": context}
    
    def _generate_system_prompt(self, context: Dict[str, Any]) -> str:
        """Generate the system prompt for the LLM."""
        receipt_type = context.get("receipt_type")
        applicable_rule = context.get("applicable_rule", "No specific rules apply.")
        
        return f"""You are an AI assistant that helps process receipts for expense reimbursement.

    RECEIPT INFORMATION:
    Type: {receipt_type}
    Content: {context.get('receipt_content')}

    APPLICABLE BUSINESS RULES:
    {applicable_rule}

    YOUR TASK:
    Analyze the receipt information and determine what actions need to be taken. You have access to the following tools:

    1. get_employee_data
    Parameters: {{ "employee_id": "EMPLOYEE_ID" }}

    2. update_expense_budget
    Parameters: {{ "employee_id": "EMPLOYEE_ID", "expense_type": "TYPE", "amount": VALUE, "increment": BOOLEAN }}

    3. check_location_proximity
    Parameters: {{ "src_address": "SOURCE_ADDRESS", "dest_address": "DESTINATION_ADDRESS" }}

    4. send_email
    Parameters: {{ "email_id": "EMAIL_ADDRESS", "subject": "EMAIL_SUBJECT", "content": "EMAIL_CONTENT" }}

    INSTRUCTIONS:
    1. First, collect all necessary information using the appropriate tools.
    2. Validate the receipt against business rules.
    3. If approved, update the relevant expense budgets.
    4. Send a notification email to the employee with the result.

    CRITICAL INSTRUCTIONS:
    - You MUST generate ONLY ONE tool call at a time.
    - NEVER generate more than one tool call in a single response.
    - Wait for the result of each tool call before deciding what to do next.
    - Strictly enforce all business rules in the applicable rule section.
    - For a receipt to be approved, it MUST satisfy ALL conditions in the business rules.

    RESPONSE FORMAT:
    You must respond using XML tags for a SINGLE tool call as follows:

    <tool_call>
    <reasoning>Your detailed reasoning about what needs to be done and why</reasoning>
    <tool>tool_name</tool>
    <parameters>
    {{
    "param1": "value1",
    "param2": "value2"
    }}
    </parameters>
    <final_tool_call>true_or_false</final_tool_call>
    </tool_call>

    For the <final_tool_call> tag, include "true" only when you are making the last tool call in the process (typically the send_email call). Otherwise, include "false".

    DO NOT include multiple <tool_call> tags in your response.
    Generate only ONE tool call per response.
    Wait for the result before making the next tool call.

    The parameters must be valid JSON. Make sure to include all required parameters for the tool you select.
    """
    
    def _parse_tool_call(self, response: str) -> Dict[str, Any]:
        """
        Parse the LLM's response to extract tool calls using regex with XML tags.
        
        Args:
            response: The LLM's response text
            
        Returns:
            A dictionary with tool name, parameters, and final_tool_call flag
        """
        try:
            # Extract the tool name
            tool_match = re.search(r"<tool>(.*?)</tool>", response, re.DOTALL)
            if not tool_match:
                return None
            
            tool_name = tool_match.group(1).strip()
            
            # Extract parameters
            params_match = re.search(r"<parameters>(.*?)</parameters>", response, re.DOTALL)
            parameters = {}
            
            if params_match:
                params_json = params_match.group(1).strip()
                parameters = json.loads(params_json)
            
            # Extract final_tool_call flag
            final_match = re.search(r"<final_tool_call>(.*?)</final_tool_call>", response, re.DOTALL)
            final_tool_call = False
            
            if final_match:
                final_str = final_match.group(1).strip().lower()
                final_tool_call = final_str in ["true", "yes", "1"]
            
            return {
                "tool": tool_name,
                "parameters": parameters,
                "final_tool_call": final_tool_call
            }
        except Exception as e:
            print(f"Error parsing tool call: {e}")
            return None
    
    async def _execute_tool(self, tool_name: str, parameters: Dict[str, Any]):
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
            
            if asyncio.iscoroutinefunction(tool_func):
                result = await tool_func(**exec_params)
            else:
                result = tool_func(**exec_params)
            
            return result
        except Exception as e:
            return {"error": f"Error executing tool {tool_name}: {str(e)}"}