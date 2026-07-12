import streamlit as st
from pymongo import MongoClient

# Establish connection helper
@st.cache_resource
def get_db():
    uri = st.secrets["mongo"]["uri"]
    client = MongoClient(uri)
    return client["my_database"]

db = get_db()
collection = db["my_collection"]

# --- DATABASE HELPER FUNCTIONS ---
def fetch_masterfile_from_db():
    return list(db.my_collection.find({}))

def save_masterfile_to_db(df):
    # Clear existing data and insert new data
    db.my_collection.delete_many({})
    db.my_collection.insert_many(df.to_dict('records'))

def save_request_to_db(req_data):
    db.requests.insert_one(req_data)

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

def save_masterfile_to_db(df):
    # Logic to save your masterfile
    pass

def update_request_status_in_db(req, status):
    db.requests.update_one({"_id": req["_id"]}, {"$set": {"status": status}})

def delete_request_from_db(req):
    db.requests.delete_one({"_id": req["_id"]})

def fetch_approved_requests_from_db():
    return list(db.requests.find({"status": "Approved"}))

def get_request_limits():
    return {"PTO": 1, "Wellness": 1} # Or fetch from DB
