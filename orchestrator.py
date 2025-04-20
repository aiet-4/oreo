import asyncio
from typing import TYPE_CHECKING

from models import ParsedReceipt

if TYPE_CHECKING:
    from receipt_parser import ReceiptParser
    from agents import AgentsWorker

class Orchestrator:

    def __init__(
        self,
        receipt_parser: 'ReceiptParser',
        agents_worker: 'AgentsWorker'
    ):
        self.receipt_parser = receipt_parser
        self.agents_worker = agents_worker


    async def orchestrate(
        self,
        img_base64: str,
        file_id: str,
    ):
        
        parsed_results : ParsedReceipt = await asyncio.create_task(
            self.receipt_parser.parse_receipt_from_base64(
                img_base64=img_base64,
            )
        )



        


