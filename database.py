import streamlit as st
from pymongo import MongoClient
from datetime import datetime

# --- CONNECTION ---
@st.cache_resource
def get_db():
    uri = st.secrets["mongo"]["uri"]
    client = MongoClient(uri)
    return client["my_database"]

db = get_db()
collection = db["my_collection"]

# --- STAFF FUNCTIONS ---
@st.cache_data(ttl=600)
def get_staff_list():
    try:
        cursor = collection.find({"type": "roster"})
        return {doc["name"]: {
            "bday": doc["bday"], 
            "nick": doc["nick"], 
            "rest_days": doc.get("rest_days", [])
        } for doc in cursor}
    except Exception:
        return {}

def save_staff(name, data):
    # Update Session State (caller handles this) and persist to DB
    collection.update_one({"type": "roster_list"}, {"$set": {f"data.{name}": data}}, upsert=True)

def delete_staff(name):
    collection.delete_one({"type": "roster", "name": name})
    collection.update_one({"type": "roster_list"}, {"$unset": {f"data.{name}": ""}})

def update_staff_in_db(name, update_dict):
    collection.update_one({"type": "roster", "name": name}, {"$set": update_dict})

# --- REQUEST & CASE FUNCTIONS ---
def fetch_masterfile_from_db():
    # Placeholder as requested
    return [
        {"Category": "Contact Type", "Values": "Email,Phone,Chat"},
        {"Category": "Issue", "Values": "Login,Billing,Technical"},
        {"Category": "Product Group", "Values": "Software,Hardware,Services"}
    ]

def save_request_to_db(req_data):
    db.requests.insert_one(req_data)

def delete_request_from_db(req):
    db.requests.delete_one({"_id": req["_id"]})

def update_request_status_in_db(req, status):
    db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": status}})

def fetch_approved_requests_from_db():
    return list(db.requests.find({"status": "Approved"}))

def save_case_to_db(case_data):
    db.cases.insert_one(case_data)

def fetch_cases_from_db():
    return list(db.cases.find({}))

def delete_case_from_db(case_id):
    db.cases.delete_one({"_id": case_id})

def update_case_in_db(case_id, update_dict):
    db.cases.update_one({"_id": case_id}, {"$set": update_dict})

def save_deviation_to_db(dev_data):
    db.deviations.insert_one(dev_data)

def fetch_deviations_from_db():
    return list(db.deviations.find({}))

def update_deviation_in_db(dev_id, update_dict):
    db.deviations.update_one({"_id": dev_id}, {"$set": update_dict})

def delete_deviation_from_db(dev_id):
    db.deviations.delete_one({"_id": dev_id})

def get_request_limits():
    return {"PTO": 1, "Wellness": 1}

# --- NOTIFICATION ---
def send_request_notification(recipient_email, status, request_type, date):
    # This assumes 'gmail_bard' is configured in your main app or accessible scope
    subject = f"Your {request_type} Request has been {status.upper()}"
    body = f"Hello,\n\nYour {request_type} request for {date} has been {status}.\n\nBest regards,\nAdmin Team"
    # Note: Ensure gmail_bard is passed in or accessible globally
    if 'gmail_bard' in globals():
        gmail_bard.send_message(to=[recipient_email], subject=subject, body=body)
