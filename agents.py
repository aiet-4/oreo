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
            office_address="OSI Systems, HiTech City, Hyderabad"
    ):
        """
        Initialize the AgentsWorker with Redis connection
        
        Args:
            redis_host (str): Redis host address
            redis_port (int): Redis port number
            redis_db (int): Redis database number
            office_address (str): Human-readable office address
        """
        # Initialize Google Maps client
        self.gmaps = googlemaps.Client(key=google_maps_key)

        # Initialize SendGrid client
        self.sg = SendGridAPIClient(sendgrid_api_key)
        
        # Initialize Redis connection
        self.redis = redis.Redis(host=redis_host, port=redis_port, db=redis_db, password=None)
        
        # Geocode the office address to get coordinates
        try:
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
                self.office_location = (17.4508, 78.3798)  # Approximate coordinates for HiTech City, Hyderabad
                self.office_address = office_address
                print(f"Could not geocode office address, using default coordinates: {self.office_location}")
        except Exception as e:
            # Fallback to default coordinates if there's an error
            self.office_location = (17.4508, 78.3798)  # Approximate coordinates for HiTech City, Hyderabad
            self.office_address = office_address
            print(f"Error geocoding office address: {e}, using default coordinates: {self.office_location}")
        
        # Initialize dummy employee data in Redis for demonstration
        self._initialize_dummy_data()
    
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
            current_amount = employee_data["expenses"].get(expense_type, 0)
            if increment:
                employee_data["expenses"][expense_type] = current_amount + amount
            else:
                employee_data["expenses"][expense_type] = max(0, current_amount - amount)
            
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
        try:
                        
            # Geocode the addresses to get coordinates
            src_geocode = [{
                'geometry': {
                    'location': {
                        'lat': 17.4508,
                        'lng': 78.3798
                    }
                }
            }]
            dest_geocode = [{
                'geometry': {
                    'location': {
                        'lat': 17.4411,
                        'lng': 78.3911
                    }
                }
            }]

            # src_geocode = self.gmaps.geocode(src_address)
            # dest_geocode = self.gmaps.geocode(dest_address)
            
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
            
            # Check if either is within 2.5km
            return src_distance <= 2.5 or dest_distance <= 2.5
            
        except Exception as e:
            print(f"Error checking location proximity: {e}")
            return False
    
    def is_duplicate_receipt(self, receipt_data, **kwargs):
        """
        Check if receipt/invoice is a duplicate
        
        Args:
            receipt_data (dict): Receipt data to check
            
        Returns:
            bool: True if duplicate, False otherwise
        """
        """
        Have to create a receipt_json fle which stores every reimbursed receipt's data
        """
        try:
            with open("receipt_data.json", "r") as file: 
                receipts = json.load(file)
        except Exception as e:
            print(f"Error loading receipt data: {e}")
        for receipt in receipts:
            if(
                receipt.get("merchant", "").lower() == receipt_data.get("Merchant/Store name", "").lower() and
                receipt.get("date") == receipt_data.get("Date of purchase") and
                float(receipt.get("amount", 0)) == float(receipt_data.get("Total amount", 0))
            ):
                return True
        return False
        # Placeholder implementation
        # In a real application, you would compare the receipt against 
        # previously processed receipts using attributes like:
        # - Merchant name
        # - Date and time
        # - Total amount
        # - Transaction ID
        pass
