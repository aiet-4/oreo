# receipt_parser.py
import asyncio
import json
import re
from typing import TYPE_CHECKING
from loguru import logger
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
import base64
from models import ParsedReceipt
from together import Together
if TYPE_CHECKING:
    from embeddings_matcher import EmbeddingsMatcher


class ReceiptParser:
    def __init__(
            self, 
            together_api_key,
            api_key="123-456",
            base_url="https://2e6e-182-74-119-254.ngrok-free.app/"
        ):

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.together_client = Together(api_key=together_api_key)
        self.embeddings_matcher: 'EmbeddingsMatcher' = None
        self.update_stage = None
        with open("ocr_instructions.json", "r") as file:
            self.data_extraction_points = json.load(file)
    
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
            file_id,
            employee_id,
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
        self.update_stage(
            file_id=file_id,
            stage=2,
            details={
                "file_id" : file_id,
                "employee_id" : employee_id,
                "receipt_type" : receipt_type,
                "stage_name" : "Identified Receipt Type"
            }
        )

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

        #Check first stage duplicate receipt
        duplicate_check_task = await asyncio.create_task(
            asyncio.to_thread(
                self.embeddings_matcher.is_duplicate_receipt,
                    receipt_type=receipt_type,
                    receipt_content=response.choices[0].message.content,
            )
        )

        possible_duplicate, duplicate_receipt_data = duplicate_check_task

        self.update_stage(
            file_id=file_id,
            stage=3,
            details={
                "file_id" : file_id,
                "employee_id" : employee_id,
                "extracted_content" : response.choices[0].message.content,
                "possible_duplicate" : possible_duplicate,
                "duplicate_receipt_data" : duplicate_receipt_data,
                "stage_name" : "Content Extraction (OCR) using InternVL"
            }
        )

        return ParsedReceipt(
            receipt_type=receipt_type,
            receipt_content=response.choices[0].message.content,
            possible_duplicate_data=duplicate_receipt_data,
        )
    
    def compare_duplicate_receipts(
        self,
        original_image_base_64: str,
        duplicate_image_base_64: str,
        model="Qwen/Qwen2.5-VL-72B-Instruct",
        temperature=0.1, 
        seed=1024, 
        max_tokens=300,
    ):
        try:
            response = self.together_client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{original_image_base_64}"},
                            },
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{duplicate_image_base_64}"},
                            },
                            {
                            "type": "text",
                            "text": f"""Compare these receipts and determine if they are duplicates.
If duplicates: respond with "YES" followed by key similarities.
If NOT duplicates: respond with "NO" followed by key differences.
DO NOT fabricate data.
IMPORTANT: Limit your response to 30 words maximum, focusing only on the most critical points.
"""
                        },
                        ]
                    }
                ],
                temperature=temperature,
                seed=seed,
                max_tokens=max_tokens
            )

            print(f"Duplicate Check Response: {response.choices[0].message.content}")
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error in duplicate receipt comparison: {e}")
            return "Duplicate Check Tool was not able to process the images. Proceed with the assumption that receipt is NOT a duplicate."