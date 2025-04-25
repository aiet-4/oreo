import traceback
import googlemaps
import redis
from geopy.distance import geodesic
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
import json


class AgentsWorker:
    def __init__(
            self, 
            google_maps_key,
            sendgrid_api_key,
            redis_password,
            redis_host="localhost", 
            redis_port=6379, 
            redis_db=0,
            office_address="The Square, KG Halli, D' Souza Road, Ashok Nagar, Bengaluru, Karnataka 560001, India"
    ):
        """
        Initialize the AgentsWorker with Redis connection
        
        Args:
            redis_host (str): Redis host address
            redis_port (int): Redis port number
            redis_db (int): Redis database number
            office_address (str): Human-readable office address
        """

        self.compare_duplicate_receipts = lambda: None

        # Initialize Google Maps client
        self.gmaps = googlemaps.Client(key=google_maps_key)

        # Initialize SendGrid client
        self.sg = SendGridAPIClient(sendgrid_api_key)
        
        # Initialize Redis connection
        self.redis = redis.Redis(host=redis_host, port=redis_port, db=redis_db, password=None)
        
        # Geocode the office address to get coordinates
        try:
            if office_address == "The Square, KG Halli, D' Souza Road, Ashok Nagar, Bengaluru, Karnataka 560001, India":
                self.office_location = (12.9718501, 77.595969) 
            else:
                office_geocode = self.gmaps.geocode(office_address)
                if office_geocode:
                    self.office_location = (
                        office_geocode[0]['geometry']['location']['lat'],
                        office_geocode[0]['geometry']['location']['lng']
                    )
                    self.office_address = office_address
                    print(f"Office location set to: {self.office_location}")
                else:
                    # Fallback to default coordinates if geocoding fails
                    self.office_location = (12.9718501, 77.595969)  # Approximate coordinates for HiTech City, Hyderabad
                    self.office_address = office_address
                    print(f"Could not geocode office address, using default coordinates: {self.office_location}")
        except Exception as e:
            # Fallback to default coordinates if there's an error
            self.office_location = (12.9718501, 77.595969)   # Approximate coordinates for HiTech City, Hyderabad
            self.office_address = office_address
            print(f"Error geocoding office address: {e}, using default coordinates: {self.office_location}")
        
        # Initialize dummy employee data in Redis for demonstration
        self._clear_redis_receipts_data()
        self._initialize_dummy_data()

    def _clear_redis_receipts_data(self):
        """Clear all receipt data from Redis"""
        try:
            keys = self.redis.keys("receipt:*")
            if keys:
                self.redis.delete(*keys)
                print("Cleared all receipt data from Redis.")
            else:
                print("No receipt data found in Redis.")
        except Exception as e:
            print(f"Error clearing receipt data: {str(e)}")

    def get_employees_details(
        self
    ):
        try:
            # Fetch all employee data from Redis
            keys = self.redis.keys("employee:*")
            employees = {}
            for key in keys:
                emp_id = key.decode('utf-8').split(":")[1]
                emp_data = self.redis.get(key)
                if emp_data:
                    # Decode bytes to string before parsing JSON
                    if isinstance(emp_data, bytes):
                        emp_data = emp_data.decode('utf-8')
                    employees[emp_id] = json.loads(emp_data)
            return employees
        except Exception as e:
            print(f"Error fetching employee details: {str(e)}")
            return {}
        
    def add_employee(
        self,
        employee_id,
        employee_details
    ):
        """
        Add a new employee to Redis.
        
        Args:
            employee_details (dict): Dictionary containing employee data. 
                                     Must include an 'employee_id' key.
        Returns:
            bool: True if successfully added, False otherwise.
        """
        try:
            redis_key = f"employee:{employee_id}"
            self.redis.set(redis_key, json.dumps(employee_details))
            print(f"Added/Updated employee: {employee_id}")
            return True

        except Exception as e:
            print(f"Error adding employee: {str(e)}")
            return False

    def _initialize_dummy_data(self):
        """Initialize some dummy data in Redis for testing purposes"""
        try:
            with open("employee_data.json", "r") as file:
                employees = json.load(file)
        except Exception as e:
            print(f"Error loading employee data: {e}")
            employees = {}
        
        # Store in Redis
        for emp_id, data in employees.items():
            self.redis.set(f"employee:{emp_id}", json.dumps(data))
    
    def send_email(self, email_id, subject, content, **kwargs):
        """
        Send an email to the user with the provided content using SendGrid
        
        Args:
            email_id (str): Recipient's email address
            content (str): Email body content (HTML format)
            subject (str): Email subject line
            
        Returns:
            bool: True if email sent successfully, False otherwise
        """
        self.update_stage(
            file_id=kwargs.get("file_id"),
            stage=6,
            sub_stage=kwargs.get("max_iterations"),
            details={
                "file_id" : kwargs.get("file_id"),
                "employee_id" : kwargs.get("employee_id"),
                "email_id" : email_id,
                "subject" : subject,
                "content" : content,
                "stage_name" : "Send Email"
            }
        )
        try:            
            # Create the email
            message = Mail(
                from_email='bharatdeep.work@gmail.com',  # Fixed sender address
                to_emails=email_id,
                subject=subject,
                html_content=content)  # Assuming content is HTML
            
            # Send the email using SendGrid
            response = self.sg.send(message)
            
            # Log the response (optional)
            print(f"Email sent to: {email_id}")
            print(f"Status code: {response.status_code}")
            
            # Return success if status code is 2xx
            return 200 <= response.status_code < 300
                
        except Exception as e:
            print(f"Error sending email: {str(e)}")
            return False
    
    def get_employee_data(self, employee_id, **kwargs):
        """
        Fetch employee data based on employee ID
        
        Args:
            employee_id (str): Employee ID
            
        Returns:
            dict: Employee data or None if not found
        """
        employee_data = self.redis.get(f"employee:{employee_id}")
        self.update_stage(
            file_id=kwargs.get("file_id"),
            stage=6,
            sub_stage=kwargs.get("max_iterations"),
            details={
                "file_id" : kwargs.get("file_id"),
                "employee_id" : kwargs.get("employee_id"),
                "stage_name" : "Get Employee Details",
                "employee_data" : employee_data
            }
        )        
        if employee_data:
            # Decode bytes to string before parsing JSON
            if isinstance(employee_data, bytes):
                employee_data = employee_data.decode('utf-8')
            return json.loads(employee_data)
        return None
    
    def update_expense_budget(self, employee_id, expense_type, amount=0, increment=True, **kwargs):
        """
        Update an employee's expense budget
        
        Args:
            employee_id (str): Employee ID
            expense_type (str): One of FOOD_EXPENSE, TRAVEL_EXPENSE, TECH_EXPENSE, OTHER_EXPENSE
            amount (float): Amount to update
            increment (bool): True to increment budget, False to decrement
            
        Returns:
            bool: True if update successful, False otherwise
        """             
        try:
            # Get current employee data
            employee_data = self.get_employee_data(employee_id)
            if not employee_data:
                return False
            
            # Validate expense type
            valid_types = ["FOOD_EXPENSE", "TRAVEL_EXPENSE", "TECH_EXPENSE"]
            if expense_type not in valid_types:
                return False
            
            # Update expense
            current_amount = employee_data["current_expenses"].get(expense_type, 0)
            if increment:
                employee_data["current_expenses"][expense_type] = current_amount + int(float(amount))
                self.update_stage(
                    file_id=kwargs.get("file_id"),
                    stage=6,
                    sub_stage=kwargs.get("max_iterations"),
                    details={
                        "file_id" : kwargs.get("file_id"),
                        "employee_id" : kwargs.get("employee_id"),
                        "stage_name" : "Updating Employee Expense",
                        "update_type" : "Incrementing",
                        "from" : current_amount,
                        "to" : current_amount + int(float(amount))
                    }
                )             
            else:                
                employee_data["current_expenses"][expense_type] = max(0, current_amount - int(float(amount)))
                self.update_stage(
                    file_id=kwargs.get("file_id"),
                    stage=6,
                    sub_stage=kwargs.get("max_iterations"),
                    details={
                        "file_id" : kwargs.get("file_id"),
                        "employee_id" : kwargs.get("employee_id"),
                        "stage_name" : "Updating Employee Expense",
                        "update_type" : "Decrementing",
                        "from" : current_amount,
                        "to" : max(0, current_amount - int(float(amount)))
                    }
                )
            
            # Save updated data
            self.redis.set(f"employee:{employee_id}", json.dumps(employee_data))
            return True
            
        except Exception as e:
            print(f"Error updating expense budget: {e}")
            return False
    
    def check_location_proximity(self, src_address, dest_address, **kwargs):
        """
        Check if either source or destination is within 1km of office
        
        Args:
            src_address (str): Source address as string
            dest_address (str): Destination address as string
            
        Returns:
            bool: True if either location is within 1km of office
        """      
        # return True
        try:

            src_geocode = self.gmaps.geocode(src_address)
            dest_geocode = self.gmaps.geocode(dest_address)
            
            # Extract coordinates
            if src_geocode:
                src_location = (
                    src_geocode[0]['geometry']['location']['lat'],
                    src_geocode[0]['geometry']['location']['lng']
                )
            else:
                print(f"Could not geocode source address: {src_address}")
                return False
                
            if dest_geocode:
                dest_location = (
                    dest_geocode[0]['geometry']['location']['lat'],
                    dest_geocode[0]['geometry']['location']['lng']
                )
            else:
                print(f"Could not geocode destination address: {dest_address}")
                return False
            
            # Calculate distances
            src_distance = geodesic(src_location, self.office_location).kilometers
            dest_distance = geodesic(dest_location, self.office_location).kilometers
            
            print(f"Source distance: {src_distance} km")
            print(f"Destination distance: {dest_distance} km")
            # Check if either is within 2.5km

            self.update_stage(
                file_id=kwargs.get("file_id"),
                stage=6,
                sub_stage=kwargs.get("max_iterations"),
                details={
                    "file_id" : kwargs.get("file_id"),
                    "employee_id" : kwargs.get("employee_id"),
                    "stage_name" : "Checking Location Proximity to Office",
                    "nearby" : src_distance <= 2.5 or dest_distance <= 2.5,
                    "src" : src_location,
                    "dest" : dest_location,
                    "office" : self.office_location
                }
            ) 
            return src_distance <= 2.5 or dest_distance <= 2.5
            
        except Exception as e:
            print(f"Error checking location proximity: {e}")
            return False
    
    def is_duplicate_receipt(
        self, 
        origin_image_base_64,
        possible_duplicate_data,
        **kwargs
    ):
        try:
            duplicate_receipts_comment = self.compare_duplicate_receipts(
                original_image_base_64=origin_image_base_64,
                duplicate_image_base_64=possible_duplicate_data["matching_receipt_image"],
            )

            self.update_stage(
                file_id=kwargs.get("file_id"),
                stage=6,
                sub_stage=kwargs.get("max_iterations"),
                details={
                    "file_id" : kwargs.get("file_id"),
                    "employee_id" : kwargs.get("employee_id"),
                    "stage_name" : "Duplicate Check using Large VLM",
                    "comment" : duplicate_receipts_comment
                }
            ) 
            return duplicate_receipts_comment
        except Exception as e:
            print(f"Error checking for duplicate receipts: {str(e)} | {traceback.format_exc()}")
            return "Duplicate Check Tool was not able to process the images. Proceed with the assumption that receipt is NOT a duplicate."
        
    def update_stage(
        self,
        file_id,
        stage,
        details,
        sub_stage=None
    ):
        try:
            # Create a Redis key for the file
            file_key = f"files:{file_id}"
            
            # If sub_stage exists, include it in the stage key
            if sub_stage is not None:
                stage_key = f"{file_key}:stage:{stage}:{sub_stage}"
            else:
                stage_key = f"{file_key}:stage:{stage}"
            
            # Store stage details under the stage-specific key
            details["stage"] = stage
            if sub_stage:
                details["sub_stage"] = sub_stage
            self.redis.set(stage_key, json.dumps(details))
            return True

        except Exception as e:
            print(f"Error updating stage: {str(e)}")
            return False
        
    def get_all_files_details(
        self
    ):
        try:
            # Fetch all employee data from Redis
            keys = self.redis.keys("files:*")
            employees = {}
            for key in keys:
                emp_id = key.decode('utf-8').split(":")[1]
                emp_data = self.redis.get(key)
                if emp_data:
                    # Decode bytes to string before parsing JSON
                    if isinstance(emp_data, bytes):
                        emp_data = emp_data.decode('utf-8')
                    employees[emp_id] = json.loads(emp_data)
            return employees
        except Exception as e:
            print(f"Error fetching files details: {str(e)}")
            return {}