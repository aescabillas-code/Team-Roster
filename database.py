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

# Define your helper functions here
def fetch_masterfile_from_db():
    # Example logic:
    return list(db.master_collection.find({}))

def save_staff(name, data):
    collection.update_one({"name": name}, {"$set": data}, upsert=True)

def delete_staff(name):
    collection.delete_one({"name": name})

def save_request_to_db(request_data):
    db.requests.insert_one(request_data)

# Add all your other functions (fetch_cases, save_case, etc.) here...
