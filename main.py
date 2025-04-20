# main.py
import base64
import asyncio
import uuid
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from orchestrator import Orchestrator
from receipt_parser import ReceiptParser
from loguru import logger

# Create a receipt parser instance
receipt_parser = ReceiptParser()
logger.success("Receipt parser Initialized.")

orchestrator = Orchestrator(
    receipt_parser=receipt_parser,
)
logger.success("Orchestrator Initialized")

app = FastAPI(title="Receipt Processing API")


@app.post("/processReceipt")
async def upload_receipt(receipt: UploadFile = File(...)):
    """
    Upload a receipt image for processing
    
    The processing happens asynchronously, and the endpoint returns immediately
    """
    try:

        file_id = str(uuid.uuid4())
        # Read the content of the uploaded file
        contents = await receipt.read()
        
        # Convert to base64
        img_base64 = base64.b64encode(contents).decode("utf-8")
        
        # Start processing in the background without waiting
        asyncio.create_task(
            orchestrator.orchestrate(
                img_base64=img_base64,
                file_id=file_id
            )
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "message": "Receipt accepted for processing", 
                "file_id": file_id
            }
        )
    
    except Exception as e:
        logger.error(f"Error handling upload: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "An error occurred while processing your request"}
        )