import asyncio
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion
import base64

class ReceiptParser:
    def __init__(self, api_key="123-456", base_url="https://2e6e-182-74-119-254.ngrok-free.app/v1"):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
    
    def _encode_image(self, image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")
    
    async def parse_receipt(
            self, 
            image_path, 
            temperature=0.1, 
            seed=1024, 
            max_tokens=512,
            model="OpenGVLab/InternVL3-2B"        
    ):
        """
        Parses a receipt image and extracts structured information.
        
        Args:
            image_path (str): Path to the receipt image file
            temperature (float): Model temperature parameter
            seed (int): Random seed for model
            max_tokens (int): Maximum tokens for response
            
        Returns:
            str: Structured receipt information
        """
        img_base64 = self._encode_image(image_path)
        
        response : ChatCompletion = asyncio.create_task(
            asyncio.to_thread(
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
Please analyze this receipt image and extract the following information in a structured format:
- Receipt Type ( Only Four Types Allowed: "FOOD_EXPENSE", "TECH_EXPENSE", "TRAVEL_EXPENSE", "OTHER_EXPENSE")
- Merchant/Store name
- Date of Purchase
- Time of Purchase
- Receipt/transaction number
- Payment method (cash, credit card, etc.)
- CGST (Amount)
- SGST (Amount)
- Sub Total
- Total amount

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
        
        return response.choices[0].message.content