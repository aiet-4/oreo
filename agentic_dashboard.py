import streamlit as st
import redis
import json
import time
import pandas as pd
from datetime import datetime

# Set up page configuration
st.set_page_config(
    page_title="Employee Expense Dashboard",
    page_icon="💼",
    layout="wide",
)

# Redis connection
@st.cache_resource
def get_redis_connection():
    return redis.Redis(
        host="localhost",
        port=6379,
        db=0,
        password=None,
        decode_responses=True
    )

# Function to fetch all employee data
def fetch_employee_data():
    r = get_redis_connection()
    employees = []
    
    # Get all keys matching employee pattern
    keys = r.keys("employee:*")
    
    for key in keys:
        # Get employee data
        emp_data_str = r.get(key)
        if emp_data_str:
            try:
                emp_data = json.loads(emp_data_str)
                # Add employee ID to the data
                emp_id = key.replace("employee:", "")
                emp_data["employee_id"] = emp_id
                employees.append(emp_data)
            except json.JSONDecodeError:
                st.error(f"Error decoding JSON for {key}")
    
    return employees

# App title
st.title("🏢 Employee Expense Dashboard")
st.markdown("Real-time monitoring of employee expense data")

# Create tabs
tab2 = st.tabs(["Expense Details"])

# Auto-refresh logic
refresh_placeholder = st.empty()
with refresh_placeholder.container():
    auto_refresh = st.checkbox("Auto-refresh data (every 5 seconds)", value=True, key="auto_refresh_checkbox")
    last_refresh = st.empty()

# Initialize session state for refresh counter
if 'refresh_count' not in st.session_state:
    st.session_state.refresh_count = 0

while True:
    # Increment refresh counter for unique keys
    st.session_state.refresh_count += 1
    current_refresh = st.session_state.refresh_count
    
    # Fetch latest data
    employees_data = fetch_employee_data()
    current_time = datetime.now().strftime("%H:%M:%S")
    last_refresh.text(f"Last refreshed: {current_time}")
    
    if employees_data:
        # Convert to DataFrame for easier manipulation
        df = pd.DataFrame(employees_data)
        
        # Extract expense data
        expense_data = []
        for employee in employees_data:
            emp_id = employee['employee_id']
            name = employee['name']
            for exp_type, amount in employee.get('expenses', {}).items():
                expense_data.append({
                    'Employee ID': emp_id,
                    'Name': name,
                    'Expense Type': exp_type,
                    'Amount': amount
                })
        expense_df = pd.DataFrame(expense_data)
        
        # Tab 2: Expense Details
        with tab2[0]:
            st.subheader("Expense Breakdown")
            
            if not expense_df.empty:
                # Add filters
                st.markdown("### Filters")
                col1, col2 = st.columns(2)
                with col1:
                    selected_employees = st.multiselect(
                        "Select Employees", 
                        options=expense_df['Name'].unique(),
                        default=expense_df['Name'].unique(),
                        key=f"emp_select_{current_refresh}"  # Add unique key
                    )
                
                with col2:
                    selected_expense_types = st.multiselect(
                        "Select Expense Types",
                        options=expense_df['Expense Type'].unique(),
                        default=expense_df['Expense Type'].unique(),
                        key=f"exp_type_select_{current_refresh}"  # Add unique key
                    )
                
                # Filter the dataframe
                filtered_df = expense_df[
                    (expense_df['Name'].isin(selected_employees)) &
                    (expense_df['Expense Type'].isin(selected_expense_types))
                ]
                
                st.dataframe(filtered_df, use_container_width=True, key=f"filtered_df_{current_refresh}")
                
                # Summary statistics
                st.markdown("### Summary Statistics")
                total_by_type = filtered_df.groupby('Expense Type')['Amount'].sum().reset_index()
                st.dataframe(total_by_type, use_container_width=True, key=f"total_by_type_{current_refresh}")
            else:
                st.info("No expense data available")
        
    else:
        st.warning("No employee data found in Redis. Please check your connection.")
    
    # Refresh logic
    if auto_refresh:
        time.sleep(5)  # Wait for 5 seconds
    else:
        st.button("Refresh Data", key=f"manual_refresh_{current_refresh}")
        break  # Exit the loop if auto-refresh is disabled