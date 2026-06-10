import pandas as pd
import requests

from ebay_client import get_access_token


SEARCH_TERMS = [
    "estate jewelry",
    "vintage ring",
    "old ring",
    "yellow metal ring",
    "jewelry lot",
    "antique ring",
    "unmarked ring",
    "vintage jewelry",
    "estate ring",
]


BAD_MATERIAL_TERMS = [
    "gold plated",
    "gold filled",
    "vermeil",
    "hge",
    "rolled gold",
    "gold tone",
    "goldtone",
    "gp",
]


GOOD_GOLD_SIGNALS = [
    "14k",
    "10k",
    "9k",
    "8k",
    "585",
    "417",
    "375",
    "333",
    "solid gold",
    "tested gold",
]


VINTAGE_SIGNALS = [
    "vintage",
    "estate",
    "old",
    "antique",
    "grandma",
    "heirloom",
]


def score_listing(title: str, price: float | None, seller_username: str | None) -> int:
    score = 0
    text = (title or "").lower()
    seller = (seller_username or "").lower()

    for term in GOOD_GOLD_SIGNALS:
        if term in text:
            score += 25

    for term in VINTAGE_SIGNALS:
        if term in text:
            score += 10

    if "not gold filled" in text or "not plated" in text:
        score += 15

    for term in BAD_MATERIAL_TERMS:
        if term in text and f"not {term}" not in text:
            score -= 60

    if price is not None:
        if price < 50:
            score += 20
        elif price < 100:
            score += 15
        elif price < 200:
            score += 8

    professional_seller_signals = [
        "jewelry",
        "jewelers",
        "diamond",
        "gold",
        "gems",
        "fine",
    ]

    if any(term in seller for term in professional_seller_signals):
        score -= 10

    return score


def search_items(query: str, limit: int = 20) -> list[dict]:
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
    response.raise_for_status()

    data = response.json()
    items = data.get("itemSummaries", [])

    results = []

    for item in items:
        title = item.get("title")
        price_raw = item.get("price", {}).get("value")
        currency = item.get("price", {}).get("currency")
        seller_username = item.get("seller", {}).get("username")
        item_url = item.get("itemWebUrl")
        image_url = item.get("image", {}).get("imageUrl")

        try:
            price = float(price_raw) if price_raw else None
        except ValueError:
            price = None

        score = score_listing(title, price, seller_username)

        results.append(
            {
                "search_term": query,
                "score": score,
                "title": title,
                "price": price,
                "currency": currency,
                "seller": seller_username,
                "url": item_url,
                "image_url": image_url,
            }
        )

    return results


def main():
    all_results = []

    for term in SEARCH_TERMS:
        print(f"Searching: {term}")
        results = search_items(term, limit=20)
        all_results.extend(results)

    df = pd.DataFrame(all_results)

    if df.empty:
        print("No results found.")
        return

    df = df.drop_duplicates(subset=["url"])
    df = df.sort_values(by="score", ascending=False)

    print(df[["score", "search_term", "title", "price", "seller", "url"]].head(20))

    df.to_csv("ebay_candidates.csv", index=False)
    print("Saved results to ebay_candidates.csv")


if __name__ == "__main__":
    main()