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
from models import AddEmployee
import os

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


@app.get("/getEmployeeDetails")
async def get_employee_details():
    """
    Get employee details from Redis
    """
    try:
        all_employees_data = agents_worker.get_employees_details()
        return {
            "message": "Employee details retrieved successfully",
            "data": all_employees_data
        }
    except Exception as e:
        logger.error(f"Error retrieving employee details: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "An error occurred while retrieving employee details"}
        )
    
@app.post("/addEmployee")
async def add_employee(
    emplpoyee_data : AddEmployee
):
    """
    Add Employee to Redis
    """
    try:
        addition_success = agents_worker.add_employee(
            employee_id=emplpoyee_data.employee_id,
            employee_details=emplpoyee_data.employee_details
        )
        return {
            "message": "Employee details added successfully",
            "data": addition_success
        }
    except Exception as e:
        logger.error(f"Error adding employee details: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "An error occurred while retrieving employee details"}
        )
    
@app.get("/getAllFiles")
async def get_employee_details():
    """
    Get employee details from Redis
    """
    try:
        all_employees_data = agents_worker.get_all_files_details()
        return {
            "message": "file details retrieved successfully",
            "data": all_employees_data
        }
    except Exception as e:
        logger.error(f"Error retrieving file details: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "An error occurred while retrieving file details"}
        )
    

@app.get("/clearAllRedisData")
async def clear_all_redis_data():
    """
    Clear all redis data
    """
    try:
        clear_success = agents_worker.clear_files_and_duplicates()
        return {
            "message": "All Data Cleared Successfully",
            "data": clear_success
        }
    except Exception as e:
        logger.error(f"Error clearing redis data: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"error": "An error occurred while clearing redis data"}
        )
    
@app.post("/processReceipt")
async def upload_receipt(
    employee_id: str = Form(...),
    receipt_base_64: str = Form(None),
    receipt: UploadFile = File(None)
):    
    """
    Upload a receipt image for processing
    
    The processing happens asynchronously, and the endpoint returns immediately
    """
    try:
        if not receipt_base_64 and not receipt:
            return JSONResponse(
                status_code=400,
                content={"error": "Either receipt_base_64 or receipt file must be provided"}
            )

        file_id = str(uuid.uuid4())
        img_base64 = receipt_base_64

        # If receipt_base_64 is not provided, read and convert the uploaded file
        if not receipt_base_64 and receipt:
            contents = await receipt.read()
            img_base64 = base64.b64encode(contents).decode("utf-8")

        agents_worker.update_stage(
            file_id=file_id,
            stage=1,
            details={
                "file_id" : file_id,
                "employee_id" : employee_id,
                "img_base64" : img_base64,
                "stage_name" : "Processing Starts"
            }
        )
        
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