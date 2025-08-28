import os
import json
import firebase_admin
from firebase_admin import credentials, auth, firestore

def init_firebase():
    if firebase_admin._apps:
        return
    json_str = os.getenv("FIREBASE_CREDENTIALS_JSON")
    if json_str:
        cred = credentials.Certificate(json.loads(json_str))
    else:
        # Dev only: load from local key file
        path = os.getenv("FIREBASE_CREDENTIALS_PATH", "firebase-admin-key.json")
        cred = credentials.Certificate(path)
    firebase_admin.initialize_app(cred)

def verify_id_token(id_token: str):
    init_firebase()
    return auth.verify_id_token(id_token)

def get_db():
    init_firebase()
    return firestore.client()

