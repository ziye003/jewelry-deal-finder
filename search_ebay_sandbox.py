import base64
import os

import requests
from dotenv import load_dotenv

load_dotenv()


def get_access_token():
    client_id = os.getenv("EBAY_CLIENT_ID")
    client_secret = os.getenv("EBAY_CLIENT_SECRET")

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
    response.raise_for_status()
    return response.json()["access_token"]


def search_items(query="14k gold ring", limit=10):
    token = get_access_token()

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    params = {
        "q": query,
        "limit": limit,
    }

    response = requests.get(url, headers=headers, params=params)
    print("Status code:", response.status_code)

    if response.status_code != 200:
        print(response.text)
        return

    data = response.json()
    items = data.get("itemSummaries", [])

    print(f"Found {len(items)} items")

    for i, item in enumerate(items, start=1):
        title = item.get("title")
        price = item.get("price", {}).get("value")
        currency = item.get("price", {}).get("currency")
        url = item.get("itemWebUrl")

        seller_username = item.get("seller", {}).get("username")
        score = score_listing(title or "", price, seller_username)

        print("-" * 60)
        print(i)
        print("Score:", score)
        print("Title:", title)
        print("Price:", price, currency)
        print("Seller:", seller_username)
        print("URL:", url)


def score_listing(title, price, seller_username):
    score = 0
    text = title.lower()

    if "14k" in text or "585" in text:
        score += 30
    if "10k" in text or "417" in text:
        score += 25
    if "9k" in text or "375" in text:
        score += 20

    if "gold filled" in text and "not gold filled" not in text:
        score -= 50
    if "gold plated" in text or "vermeil" in text or "hge" in text:
        score -= 50

    if "vintage" in text or "estate" in text or "old" in text:
        score += 10

    if price and float(price) < 150:
        score += 15

    return score

if __name__ == "__main__":
    search_items("14k gold ring", limit=10)