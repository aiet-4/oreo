from pydantic import BaseModel

class ParsedReceipt(BaseModel):
    receipt_type: str
    receipt_content: str