# receipt_parser.py
import asyncio
import re
from loguru import logger
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
import base64

from models import ParsedReceipt

class ReceiptParser:
    def __init__(
            self, 
            api_key="123-456", 
            base_url="https://2e6e-182-74-119-254.ngrok-free.app/"
        ):
        self.client = OpenAI(api_key=api_key, base_url=base_url)

        self.data_extraction_points = {
            "FOOD_EXPENSE" : f"""
- Merchant/Store name
- Date of Purchase
- Time of Purchase
- Receipt/transaction number
- Payment method (cash, credit card, etc.)
- Total Tax ( Use if CGST and SGST are not available)
- Total amount
""",
            "TRAVEL_EXPENSE" : f"""
- Merchant/Store Name
- Date of Purchase
- Time of Purchase
- Date of Travel
- Time of Travel
- Travelling Mode (Taxi Cab, Flight, Train, Bus, etc.)
- Jounrey Start Point
- Journey End Point 
- Total amount
""",
            "TECH_EXPENSE" : f"""
- Merchant/Store Name
- Date of Purchase
- Purchase Mode (Online, Offline)
- Product Name
- Product Category (Laptop, Mobile, etc.)
- Product Model
- Product Serial Number
- Payment Mode (cash, credit card, etc.)
- Total Tax
- Total Amount
""",
            "OTHER_EXPENSE" : f"""
Describe the receipt in LESS THAN 30 words
"""
        }
    
    def _encode_image(
            self, 
            image_path
        ):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
        
    def extract_receipt_type(self, content):
        """
        Extracts the receipt type from parsed content using regex.
        
        Args:
            content (str): The parsed receipt content
            
        Returns:
            str: One of "FOOD_EXPENSE", "TRAVEL_EXPENSE", "TECH_EXPENSE", or "OTHER_EXPENSE"
        """
        # First, try to match the content directly as one of the valid types
        content = content.strip().upper()
        valid_types = ["FOOD_EXPENSE", "TRAVEL_EXPENSE", "TECH_EXPENSE", "OTHER_EXPENSE"]
        
        if content in valid_types:
            return content
        
        # If that fails, try the more complex regex pattern
        pattern = r"(?:Receipt Type|Type|Category)(?:\s*:|\s*-|\s*)?\s*(FOOD_EXPENSE|TRAVEL_EXPENSE|TECH_EXPENSE|OTHER_EXPENSE)"
        
        # Search using case-insensitive matching
        match = re.search(pattern, content, re.IGNORECASE)
        
        if match:
            # Get the matched type and convert to uppercase to ensure consistency
            receipt_type = match.group(1).upper()
            
            # Validate that it's one of the allowed types
            if receipt_type in valid_types:
                return receipt_type
        
        # If no valid match found, default to OTHER_EXPENSE
        return "OTHER_EXPENSE"

    async def parse_receipt_from_base64(
            self, 
            img_base64,
            temperature=0.1, 
            seed=1024, 
            max_tokens=512,
            model="vlm"        
    )-> ParsedReceipt:

        response : ChatCompletion = await asyncio.create_task(asyncio.to_thread(
            self.client.chat.completions.create,
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                        },
                        {
                            "type": "text",
                            "text": f"""
A receipt/invoice is provided in the iamge. Classify it into one of the following categories:
1. FOOD_EXPENSE
2. TRAVEL_EXPENSE
3. TECH_EXPENSE
4. OTHER_EXPENSE

Only respond with the category name. Do not include any other text.
""",
                        },
                    ],
                }
            ],
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens
        ))
        
        receipt_type = self.extract_receipt_type(response.choices[0].message.content)
        logger.success(f"Receipt Type: {receipt_type}")


        response : ChatCompletion = await asyncio.create_task(asyncio.to_thread(
            self.client.chat.completions.create,
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_base64}"},
                        },
                        {
                            "type": "text",
                            "text": f"""
Please analyze this receipt image and extract the following information in this EXACT structured format:

{self.data_extraction_points[receipt_type]}

NOTE:
1. DO NOT FABRICATE any data if not available or unclear
2. Only answer the above information, NOTHING extra
""",
                        },
                    ],
                }
            ],
            temperature=temperature,
            seed=seed,
            max_tokens=max_tokens
        ))

        logger.success(f"Receipt Data Extracted: {response.choices[0].message.content}")

        return ParsedReceipt(
            receipt_type=receipt_type,
            receipt_content=response.choices[0].message.content
        )