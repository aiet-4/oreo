from typing import Optional
from pydantic import BaseModel

class ParsedReceipt(BaseModel):
    receipt_type: str
    receipt_content: str
    possible_duplicate_data: Optional[dict] = None


class AddEmployee(BaseModel):
    employee_id: str
    employee_details: dict
