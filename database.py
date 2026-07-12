import streamlit as st
from pymongo import MongoClient

# Establish connection
@st.cache_resource
def get_db():
    uri = st.secrets["mongo"]["uri"]
    client = MongoClient(uri)
    return client["my_database"]

db = get_db()
collection = db["my_collection"]

def fetch_masterfile_from_db():
    # Replace this with your actual database logic
    # Example:
    # return list(db.my_collection.find({}))
    
    # Placeholder for testing:
    return [
        {"Category": "Contact Type", "Values": "Email,Phone,Chat"},
        {"Category": "Issue", "Values": "Login,Billing,Technical"},
        {"Category": "Product Group", "Values": "Software,Hardware,Services"}
    ]
    
# 2. NOW DEFINE THE FUNCTION (it can now see 'collection')
        
@st.cache_data(ttl=600)
def get_staff_list():
    try:
        # Fetching documents from MongoDB
        cursor = collection.find({"type": "roster"})
        # Building the dictionary
        return {doc["name"]: {
            "bday": doc["bday"], 
            "nick": doc["nick"], 
            "rest_days": doc.get("rest_days", [])
        } for doc in cursor}
    except Exception as e:
        # If there's a connection error or query issue, show error and return empty dict
        st.error("Could not load staff data from the database.")
        return {}

def save_staff(name, data):
    # 1. Update Session State (for immediate UI response)
    st.session_state.staff_roster[name] = data
    
    # 2. Update Database (for persistence)
    collection.update_one(
        {"type": "roster_list"},
        {"$set": {"data": st.session_state.staff_roster}},
        upsert=True
    )

def delete_staff(name):
    # 1. Remove from MongoDB
    collection.delete_one({"type": "roster", "name": name})
    
    # 2. Update session state immediately so the UI reflects the change
    if name in st.session_state.staff_roster:
        del st.session_state.staff_roster[name]
        
    st.success(f"{name} has been removed.")

def update_staff_in_db(name, update_dict):
    # 1. Update in MongoDB
    collection.update_one({"type": "roster", "name": name}, {"$set": update_dict})
    
    # 2. Update session state so the UI reflects the change
    if name in st.session_state.staff_roster:
        st.session_state.staff_roster[name].update(update_dict)
        
    st.success(f"{name} has been updated.")
    
# --- DATABASE ---
uri = st.secrets["mongo"]["uri"]

@st.cache_resource
def get_db_client():
    return MongoClient(uri)

def get_collection():
    client = get_db_client()
    return client["my_database"]["my_collection"]

# --- HANDLER FUNCTIONS ---
def handle_approval(req, original_idx):
    # 1. Add to approved list
    st.session_state.approved_requests.append(req)
    
    # 2. Remove from pending list
    st.session_state.pending_requests.pop(original_idx)
    
    # 3. Send Email
    if req.get("email"):
        send_request_notification(req['email'], "Approved", req['type'], req['date'])
        
    # 4. Set Success Message
    st.session_state.admin_msg = ("success", f"Approved {req['name']}'s {req['type']} request.")
    
    # 5. Rerun to refresh UI
    st.rerun()
    
def render_request(req, idx, key_prefix):
    # Unique keys for this specific request
    denial_key = f"denying_{key_prefix}_{idx}"
    
    # 1. Standard Display Row
    c1, c2, c3 = st.columns([3, 1, 1])
    c1.write(f"**{req['name']}** - {req['date']} ({req['type']})")
    
    # 2. Approve Action
    if c2.button("Approve", key=f"app_{key_prefix}_{idx}"):
        # Update Database
        update_request_status_in_db(req, "Approved")
        # Sync Session State
        req['status'] = "Approved"
        st.session_state.approved_requests.append(req)
        st.session_state.pending_requests.pop(idx)
        st.success("Request Approved and saved!")
        st.rerun()

    # 3. Deny Action (Triggers Popup)
    if c3.button("Deny", key=f"den_{key_prefix}_{idx}"):
        st.session_state[denial_key] = True
        st.rerun()

    # 4. Denial Popup Logic
    if st.session_state.get(denial_key):
        st.write(f"--- Reason for denying {req['name']}'s {req['type']} request ---")
        reason = st.text_input("Reason", key=f"reason_{key_prefix}_{idx}")
        
        col1, col2 = st.columns(2)
        if col1.button("Proceed Denial", key=f"confirm_{key_prefix}_{idx}"):
            # 1. Database Deletion
            delete_request_from_db(req)
            # 2. Notification (Optional)
            if req.get("email"):
                send_request_notification(req['email'], "Denied", req['type'], req['date'])
            # 3. State sync
            st.session_state.pending_requests.pop(idx)
            st.session_state[denial_key] = False
            st.session_state.admin_msg = ("warning", f"Denied {req['name']}'s request: {reason}")
            st.rerun()
            
        if col2.button("Cancel", key=f"cancel_{key_prefix}_{idx}"):
            st.session_state[denial_key] = False
            st.rerun()
            
    else:
        # --- STANDARD VIEW ---
        st.write(f"**{req['name']}** | {req['type']} | {req['date']}")
        
        c1, c2 = st.columns(2)
        # Call the handle_approval function here
        if c1.button("Approve", key=f"app_{key_prefix}_{idx}"):
            handle_approval(req, idx) 
            
        if c2.button("Deny", key=f"den_{key_prefix}_{idx}"):
            st.session_state[denial_key] = True
            st.rerun()
            
def send_request_notification(recipient_email, status, request_type, date):
    # Everything below MUST be indented with 4 spaces (or one tab)
    subject = f"Your {request_type} Request has been {status.upper()}"
    body = f"Hello,\n\nYour {request_type} request for {date} has been {status}.\n\nBest regards,\nAdmin Team"
    
    # Use gmail_bard to send
    gmail_bard.send_message(
        to=[recipient_email],
        subject=subject,
        body=body
    )

# --- ADD THIS MIGRATION BLOCK ---
if "staff_roster" in st.session_state:
    for name, value in st.session_state.staff_roster.items():
        # Check if the value is just a date object (the old format)
        if not isinstance(value, dict):
            # Convert the old format to the new format
            st.session_state.staff_roster[name] = {
                "bday": value, 
                "nick": name  # Default nickname to the full name
            }
