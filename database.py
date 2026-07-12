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
def load_data_from_db():
    if "staff_roster" not in st.session_state:
        roster_doc = collection.find_one({"type": "roster_list"})
        st.session_state.staff_roster = roster_doc.get("data", {}) if roster_doc else {}
    
    cal_doc = collection.find_one({"type": "calendar_data"})
    if cal_doc and "data" in cal_doc:
        # Convert string keys (from DB) back into date objects (for logic/display)
        st.session_state.calendar_data = {
            datetime.strptime(k, "%Y-%m-%d").date(): v 
            for k, v in cal_doc["data"].items()
        }
    else:
        st.session_state.calendar_data = {}
        
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
    
# --- INITIAL CONFIG & STATE ---
st.set_page_config(layout="wide", page_title="Team Roster & Staffing System")

# --- DATABASE ---
uri = st.secrets["mongo"]["uri"]

@st.cache_resource
def get_db_client():
    return MongoClient(uri)

def get_collection():
    client = get_db_client()
    return client["my_database"]["my_collection"]
