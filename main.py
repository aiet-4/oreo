# main.py
import base64
import asyncio
import uuid
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse
from orchestrator import Orchestrator
from receipt_parser import ReceiptParser
from agents import AgentsWorker
from loguru import logger
from dotenv import load_dotenv
import os
import hashlib

load_dotenv()

# Create a receipt parser instance
receipt_parser = ReceiptParser(
    together_api_key=os.getenv("TOGETHER_API_KEY"),
)
logger.success("Receipt parser Initialized.")

# Create an agents worker instance
agents_worker = AgentsWorker(
    redis_password=os.getenv("REDIS_PASSWORD"),
    google_maps_key=os.getenv("GOOGLE_MAPS_API_KEY"),
    sendgrid_api_key=os.getenv("SENDGRID_API_KEY"),
)
logger.success("Agents worker Initialized.")

orchestrator = Orchestrator(
    receipt_parser=receipt_parser,
    agents_worker=agents_worker
)
logger.success("Orchestrator Initialized")

app = FastAPI(title="Receipt Processing API")

def check_duplicate_hash(new_hash: str, hash_file_path: str = "hash.json"):
        """
    Check if the given hash already exists in the hash file.

    Args:
        new_hash (str): The SHA-256 hash of the uploaded receipt.
        hash_file_path (str): Path to the JSON file storing existing hashes.

    Returns:
        JSONResponse or None: Returns JSONResponse with 409 if duplicate, else None.
    """
    try:
        with open(hash_file_path, "r") as file:
            existing_hashes = json.load(file)
    except Exception as e:
        print(f"Error loading existing hash data: {e}")
        existing_hashes = []

    if new_hash in existing_hashes:
        return JSONResponse(
            status_code=409,
            content={"error": "Duplicate receipt detected"}
        )

    return None


@app.post("/processReceipt")
async def upload_receipt(
    employee_id: str = Form(...),
    receipt: UploadFile = File(...)
):    
    """
    Upload a receipt image for processing
    
    The processing happens asynchronously, and the endpoint returns immediately
    """
    try:

        file_id = str(uuid.uuid4())
        # Read the content of the uploaded file
        contents = await receipt.read()
        
        new_hash = hashlib.sha256(contents).hexdigest()

        dup = check_duplicate_hash(new_hash)
        if duplicate_response:
            return duplicate_response 
    
        return JSONResponse(
            status_code=200,
            content={"message": "Receipt uploaded successfully"}
        )
        
        # Convert to base64
        img_base64 = base64.b64encode(contents).decode("utf-8")
        
        # Start processing in the background without waiting
        asyncio.create_task(
            orchestrator.orchestrate(
                img_base64=img_base64,
                file_id=file_id,
                employee_id=employee_id
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
