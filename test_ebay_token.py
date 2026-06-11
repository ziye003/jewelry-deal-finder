import base64
import os

import requests
from dotenv import load_dotenv

load_dotenv()

client_id = os.getenv("EBAY_CLIENT_ID")
client_secret = os.getenv("EBAY_CLIENT_SECRET")

if not client_id or not client_secret:
    raise ValueError("Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET in .env")

credentials = f"{client_id}:{client_secret}"
encoded_credentials = base64.b64encode(credentials.encode()).decode()

url = "https://api.ebay.com/identity/v1/oauth2/token"

headers = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Authorization": f"Basic {encoded_credentials}",
}

data = {
    "grant_type": "client_credentials",
    "scope": "https://api.ebay.com/oauth/api_scope",
}

response = requests.post(url, headers=headers, data=data)

print("Status code:", response.status_code)

if response.status_code == 200:
    print("Success! Access token received.")
else:
    print(response.text)