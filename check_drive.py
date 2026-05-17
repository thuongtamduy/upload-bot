import os, json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/drive"]
creds = Credentials.from_authorized_user_file("token.json", SCOPES)
service = build("drive", "v3", credentials=creds)

with open('config.json', 'r') as f:
    config = json.load(f)

parent_id = config.get("DRIVE_FOLDER_ID")

try:
    print(f"Checking folder ID: {parent_id}")
    folder = service.files().get(fileId=parent_id, fields="id, name, capabilities").execute()
    print("Folder info:", json.dumps(folder, indent=2))
    
    about = service.about().get(fields="storageQuota").execute()
    print("Storage Quota:", json.dumps(about, indent=2))
    
    # Try a dummy upload
    body = {"name": "test_upload.txt", "parents": [parent_id]}
    req = service.files().create(body=body, media_body=None, fields="id")
    res = req.execute()
    print("Dummy upload success:", res)
    service.files().delete(fileId=res['id']).execute()
    
except HttpError as e:
    print(f"HTTP Error {e.resp.status}:")
    print(e.content.decode('utf8'))
