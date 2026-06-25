import argparse
import glob
import html
import os
from pydoc import text
import re
from datetime import date, datetime, timezone

import pandas as pd
import requests

from ebay_client import get_access_token


MASTER_CSV = "ebay_candidates_master.csv"

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
    "scrap gold ring",
    "tested gold ring",
    "585 ring",
    "375 ring",
    "9ct ring",
    "10k ring lot",
]

POSITIVE_SIGNALS = [
    "14k", "10k", "9k", "8k",
    "585", "417", "375", "333",
    "solid gold", "tested gold", "tested",
    "estate", "vintage", "antique", "old",
]

HIDDEN_GOLD_SIGNALS = [
    "yellow metal",
    "unmarked",
    "old ring",
    "jewelry lot",
    "estate lot",
    "inherited",
    "grandma",
    "misc jewelry",
]

NEGATIVE_SIGNALS = [
    "gold plated",
    "gold filled",
    "vermeil",
    "hge",
    "rolled gold",
    "gold tone",
    "costume",
    "brass",
    "stainless",
]

SILVER_OR_NON_PRECIOUS_SIGNALS = [
    "sterling",
    "sterling silver",
    "925",
    "s925",
    "silver",
    "ss",
    "stainless",
    "stainless steel",
    "steel",
    "brass",
    "copper",
    "alloy",
    "pewter",
    "costume",
]

NON_VINTAGE_SIGNALS = [
    "modern",
    "new",
    "fashion",
    "contemporary",
    "current",
]
COSTUME_BRANDS = [
    "monet", "avon", "sarah coventry", "trifari", "lisner", "napier",
    "jj", "j.j.", "park lane", "coro", "west germany", "roman",
    "1928", "goldette", "dujay", "swarovski",
]

HEAVY_NEGATIVE_SIGNALS = [
    "electroplated",
    "gold electroplate",
    "g.e.",
    " ge ",
    "rhinestone",
    "rhinestones",
    "crystal",
    "crystals",
    "gold tone",
    "silver tone",
    "unsigned",
    "wearable craft",
    "craft lot",
    "unsearched",
    "to now",
    "vintage to now",
    "huge jewelry lot",
]

PRO_SELLER_WORDS = [
    "jewelry",
    "jewelers",
    "diamond",
    "diamonds",
    "gems",
    "gold",
    "pawn",
]
GOLD_EVIDENCE = [
    "14k",
    "10k",
    "9k",
    "8k",
    "585",
    "417",
    "375",
    "333",
    "tested gold",
    "solid gold",
    "scrap gold",
    "yellow metal",
]

COLUMN_ORDER = [
    "my_score",
    "final_score",
    "title",
    "price",
    "shipping_cost",
    "total_cost",
    "image_url",
    "item_url",
    "base_score",
    "preference_score",
    "seller",
    "search_term",
    "score_reasons",
    "learned_reasons",
    "currency",
    "condition",
    "item_id",
    "date_pulled",
    "date_pulled_day",
]


def today_str():
    return date.today().isoformat()


def output_csv_name(run_date):
    return f"ebay_candidates_{run_date}.csv"


def output_html_name(run_date):
    return f"deal_report_{run_date}.html"


def tokenize(text):
    text = str(text or "").lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    return [t for t in tokens if len(t) >= 3]


def normalize_my_score(value):
    score = pd.to_numeric(value, errors="coerce")
    if pd.isna(score):
        return ""
    return score

def extract_shipping_cost(item):
    shipping_options = item.get("shippingOptions", []) or []

    for option in shipping_options:
        cost = option.get("shippingCost", {})
        value = cost.get("value")

        if value is not None:
            try:
                return float(value)
            except ValueError:
                return 0.0

    return 0.0


def load_csv_files(pattern="ebay_candidates*.csv"):
    files = sorted(glob.glob(pattern))
    files = [f for f in files if not f.endswith("_master.csv")]

    frames = []
    for file in files:
        try:
            df = pd.read_csv(file)
            df["_source_file"] = file
            frames.append(df)
        except Exception as exc:
            print(f"Skipping {file}: {exc}")

    if not frames:
        return pd.DataFrame()

    return pd.concat(frames, ignore_index=True)


def combine_and_dedupe(df):
    if df.empty:
        return df

    if "my_score" not in df.columns:
        df["my_score"] = ""

    if "item_id" not in df.columns:
        return df

    df["item_id"] = df["item_id"].astype(str)
    df["my_score_numeric"] = pd.to_numeric(df["my_score"], errors="coerce")

    rows = []

    for item_id, group in df.groupby("item_id", dropna=False):
        group = group.copy()

        reviewed_scores = group["my_score_numeric"].dropna()
        chosen = group.iloc[-1].copy()

        if len(reviewed_scores) > 0:
            chosen["my_score"] = reviewed_scores.median()
        else:
            chosen["my_score"] = ""

        rows.append(chosen.drop(labels=["my_score_numeric"], errors="ignore"))

    out = pd.DataFrame(rows)

    if "date_pulled_day" not in out.columns and "date_pulled" in out.columns:
        out["date_pulled_day"] = pd.to_datetime(out["date_pulled"], errors="coerce").dt.date.astype(str)

    return out


def build_preference_weights(existing_df):
    if existing_df.empty or "my_score" not in existing_df.columns:
        return {}

    reviewed = existing_df.copy()
    reviewed["my_score_numeric"] = pd.to_numeric(reviewed["my_score"], errors="coerce")
    reviewed = reviewed.dropna(subset=["my_score_numeric"])

    if len(reviewed) < 10:
        return {}

    word_scores = {}

    for _, row in reviewed.iterrows():
        title = row.get("title", "")
        score = row.get("my_score_numeric")

        for token in set(tokenize(title)):
            word_scores.setdefault(token, []).append(score)

    weights = {}

    for token, scores in word_scores.items():
        if len(scores) < 2:
            continue

        avg_score = sum(scores) / len(scores)

        if avg_score >= 4.2:
            weights[token] = 15
        elif avg_score >= 3.5:
            weights[token] = 8
        elif avg_score <= 1.8:
            weights[token] = -18
        elif avg_score <= 2.5:
            weights[token] = -8

    return weights

def score_listing(item):
    title = item.get("title", "") or ""
    seller = item.get("seller", {}).get("username", "") or ""
    price = float(item.get("price", {}).get("value", 0) or 0)
    shipping_cost = extract_shipping_cost(item)
    total_cost = price + shipping_cost

    text = f"{title} {seller}".lower()
    padded_text = f" {text} "
    score = 0
    reasons = []

    for word in HEAVY_NEGATIVE_SIGNALS:
        if word in padded_text:
            score -= 45
            reasons.append(f"- heavy negative: {word.strip()}")

    costume_brand_count = 0
    for brand in COSTUME_BRANDS:
        if brand in text:
            costume_brand_count += 1

    if costume_brand_count >= 2:
        score -= 100
        reasons.append("- costume jewelry brands")
    elif costume_brand_count == 1:
        score -= 60
        reasons.append("- costume jewelry brand")

    if "jewelry lot" in text or "jewellery lot" in text:
        if costume_brand_count >= 1:
            score -= 50
            reasons.append("- costume jewelry lot")
        elif not any(x in text for x in [
            "14k", "10k", "9k", "585", "417", "375",
            "tested gold", "solid gold", "scrap gold"
        ]):
            score -= 50
            reasons.append("- generic jewelry lot")

    gold_hits = sum(1 for word in GOLD_EVIDENCE if word in text)
    if gold_hits > 0:
        score += gold_hits * 10
        reasons.append(f"+ gold evidence x{gold_hits}")

    for word in POSITIVE_SIGNALS:
        if word in text:
            score += 10
            reasons.append(f"+ {word}")

    for word in HIDDEN_GOLD_SIGNALS:
        if word in text:
            score += 15
            reasons.append(f"+ hidden gold: {word}")

    for word in NEGATIVE_SIGNALS:
        if word in text:
            score -= 35
            reasons.append(f"- {word}")

    for word in SILVER_OR_NON_PRECIOUS_SIGNALS:
        if word in text:
            score -= 18
            reasons.append(f"- silver/non-precious: {word}")

    if "jewelry lot" in text or "jewellery lot" in text:
        if any(word in text for word in SILVER_OR_NON_PRECIOUS_SIGNALS):
            score -= 30
            reasons.append("- silver/non-precious jewelry lot")

    has_vintage_signal = any(word in text for word in ["vintage", "estate", "antique", "old"])
    if not has_vintage_signal:
        score -= 10
        reasons.append("- not vintage/estate/antique")

    for word in PRO_SELLER_WORDS:
        if word in seller.lower():
            score -= 15
            reasons.append(f"- pro seller: {word}")

    if total_cost <= 200:
        score += 25
        reasons.append("+ total under $200 with shipping")
    elif total_cost <= 350:
        score += 12
        reasons.append("+ total under $350 with shipping")
    elif total_cost > 800:
        score -= 20
        reasons.append("- expensive with shipping")

    if 25 <= price <= 350:
        score += 5
        reasons.append("+ good item price range")

    if len(title.split()) <= 5:
        score += 8
        reasons.append("+ short/vague title")

    return score, "; ".join(reasons)

def preference_score_listing(item, preference_weights):
    title = item.get("title", "") or ""
    tokens = set(tokenize(title))

    score = 0
    reasons = []

    for token in tokens:
        if token in preference_weights:
            weight = preference_weights[token]
            score += weight

            if weight > 0:
                reasons.append(f"+ learned: {token}")
            else:
                reasons.append(f"- learned: {token}")

    return score, "; ".join(reasons)


def search_ebay(term, limit=50):
    token = get_access_token()

    url = "https://api.ebay.com/buy/browse/v1/item_summary/search"

    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    params = {
        "q": term,
        "limit": limit,
        "sort": "newlyListed",
        "category_ids": "281",
        "filter": "price:[20..900],priceCurrency:USD,buyingOptions:{FIXED_PRICE}",
    }

    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()

    return response.json().get("itemSummaries", [])


def ensure_columns(df):
    for col in COLUMN_ORDER:
        if col not in df.columns:
            df[col] = ""

    extra_cols = [c for c in df.columns if c not in COLUMN_ORDER and not c.startswith("_")]
    return df[COLUMN_ORDER + extra_cols]


def filter_by_date(df, args, run_date):
    if df.empty:
        return df

    if "date_pulled_day" not in df.columns:
        df["date_pulled_day"] = pd.to_datetime(df["date_pulled"], errors="coerce").dt.date.astype(str)

    if args.date:
        start_date = args.date
        end_date = args.date
    elif args.start_date or args.end_date:
        start_date = args.start_date or "1900-01-01"
        end_date = args.end_date or run_date
    else:
        start_date = run_date
        end_date = run_date

    mask = (df["date_pulled_day"] >= start_date) & (df["date_pulled_day"] <= end_date)
    return df[mask].copy()


def generate_html_report(df, output_html, report_title):
    if df.empty:
        cards_html = "<p>No candidates found for this date range.</p>"
    else:
        report_df = df[df["my_score"].isna() | (df["my_score"].astype(str).str.strip() == "")]
        report_df = report_df.sort_values(by="final_score", ascending=False).head(100)

        cards = []

        for _, row in report_df.iterrows():
            title = html.escape(str(row.get("title", "")), quote=True)
            price = html.escape(str(row.get("price", "")), quote=True)
            shipping_cost = html.escape(str(row.get("shipping_cost", "")), quote=True)
            total_cost = html.escape(str(row.get("total_cost", "")), quote=True)
            seller = html.escape(str(row.get("seller", "")), quote=True)
            final_score = html.escape(str(row.get("final_score", "")), quote=True)
            base_score = html.escape(str(row.get("base_score", "")), quote=True)
            preference_score = html.escape(str(row.get("preference_score", "")), quote=True)
            reasons = html.escape(str(row.get("score_reasons", "")), quote=True)
            learned_reasons = html.escape(str(row.get("learned_reasons", "")), quote=True)
            item_url = html.escape(str(row.get("item_url", "")), quote=True)
            image_url = html.escape(str(row.get("image_url", "")), quote=True)
            item_id = html.escape(str(row.get("item_id", "")), quote=True)

            card = f"""
            <div class="card">
                <img src="{image_url}" class="item-image" />
                <div class="info">
                    <h2>{title}</h2>
                    <p class="price">${price}</p>
                    <p><b>Shipping:</b> ${shipping_cost} | <b>Total:</b> ${total_cost}</p>
                    <p><b>Final Score:</b> {final_score}</p>
                    <p><b>Base Score:</b> {base_score} | <b>Preference Score:</b> {preference_score}</p>
                    <p><b>Seller:</b> {seller}</p>
                    <p class="reasons"><b>Rule reasons:</b> {reasons}</p>
                    <p class="learned"><b>Learned reasons:</b> {learned_reasons}</p>

                    <a href="{item_url}" target="_blank">Open eBay Listing</a>

                    <button class="bought-button"
                        onclick="markBought(this)"
                        data-item-id="{item_id}"
                        data-title="{title}"
                        data-price="{price}"
                        data-shipping-cost="{shipping_cost}"
                        data-total-cost="{total_cost}"
                        data-seller="{seller}"
                        data-final-score="{final_score}"
                        data-base-score="{base_score}"
                        data-preference-score="{preference_score}"
                        data-item-url="{item_url}"
                        data-image-url="{image_url}">
                        Bought
                    </button>
                </div>
            </div>
            """
            cards.append(card)

        cards_html = "".join(cards)

    html_text = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>{html.escape(report_title)}</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f7f4ef;
                margin: 24px;
            }}
            .card {{
                display: flex;
                gap: 20px;
                background: white;
                padding: 16px;
                margin-bottom: 18px;
                border-radius: 12px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            }}
            .item-image {{
                width: 220px;
                height: 220px;
                object-fit: cover;
                border-radius: 8px;
                background: #eee;
            }}
            h1 {{
                margin-bottom: 4px;
            }}
            h2 {{
                margin-top: 0;
                font-size: 20px;
            }}
            .price {{
                font-size: 22px;
                font-weight: bold;
                color: #7a4a16;
            }}
            .reasons {{
                color: #555;
                font-size: 14px;
            }}
            .learned {{
                color: #8a4b00;
                font-size: 14px;
            }}
            a, button {{
                display: inline-block;
                margin-top: 8px;
                margin-right: 8px;
                color: white;
                background: #333;
                padding: 8px 12px;
                border-radius: 6px;
                text-decoration: none;
                border: none;
                cursor: pointer;
                font-size: 14px;
            }}
            .bought-button {{
                background: #7a4a16;
            }}
            .bought-button:disabled {{
                background: #999;
                cursor: not-allowed;
            }}
            .download-button {{
                background: #1f5f3f;
                margin-bottom: 18px;
            }}
        </style>
    </head>

    <body>
        <h1>{html.escape(report_title)}</h1>
        <p>Showing unreviewed candidates only. Fill <b>my_score</b> in the CSV after review.</p>

        <button class="download-button" onclick="downloadBoughtCSV()">Download bought_items.csv</button>

        {cards_html}

        <script>
            function getBoughtItems() {{
                return JSON.parse(localStorage.getItem("bought_items") || "[]");
            }}

            function saveBoughtItems(items) {{
                localStorage.setItem("bought_items", JSON.stringify(items));
            }}

            function markBought(button) {{
                const item = {{
                    bought_date: new Date().toISOString(),
                    item_id: button.dataset.itemId,
                    title: button.dataset.title,
                    price: button.dataset.price,
                    shipping_cost: button.dataset.shippingCost,
                    total_cost: button.dataset.totalCost,
                    seller: button.dataset.seller,
                    final_score: button.dataset.finalScore,
                    base_score: button.dataset.baseScore,
                    preference_score: button.dataset.preferenceScore,
                    item_url: button.dataset.itemUrl,
                    image_url: button.dataset.imageUrl
                }};

                let boughtItems = getBoughtItems();

                const alreadyExists = boughtItems.some(x => x.item_id === item.item_id);

                if (!alreadyExists) {{
                    boughtItems.push(item);
                    saveBoughtItems(boughtItems);
                }}

                button.innerText = "Bought ✓";
                button.disabled = true;
            }}

            function downloadBoughtCSV() {{
                const boughtItems = getBoughtItems();

                if (boughtItems.length === 0) {{
                    alert("No bought items yet.");
                    return;
                }}

                const headers = [
                    "bought_date",
                    "item_id",
                    "title",
                    "price",
                    "shipping_cost",
                    "total_cost",
                    "seller",
                    "final_score",
                    "base_score",
                    "preference_score",
                    "item_url",
                    "image_url"
                ];

                const rows = boughtItems.map(item =>
                    headers.map(h => {{
                        const value = String(item[h] || "");
                        return `"${{value.replaceAll('"', '""')}}"`;
                    }}).join(",")
                );

                const csv = [headers.join(","), ...rows].join("\\n");
                const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8;" }});
                const url = URL.createObjectURL(blob);

                const a = document.createElement("a");
                a.href = url;
                a.download = "bought_items.csv";
                a.click();

                URL.revokeObjectURL(url);
            }}
        </script>
    </body>
    </html>
    """

    with open(output_html, "w", encoding="utf-8") as f:
        f.write(html_text)


def parse_args():
    parser = argparse.ArgumentParser(description="Jewelry Deal Finder")
    parser.add_argument("--date", help="Show listings pulled on this date only, format YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start date for report, format YYYY-MM-DD")
    parser.add_argument("--end-date", help="End date for report, format YYYY-MM-DD")
    parser.add_argument("--limit", type=int, default=50, help="eBay result limit per search term")
    parser.add_argument("--skip-search", action="store_true", help="Do not call eBay API; only regenerate report from existing CSVs")
    return parser.parse_args()


def main():
    args = parse_args()
    run_date = today_str()

    daily_csv = output_csv_name(run_date)
    daily_html = output_html_name(run_date)

    historical_df = load_csv_files("ebay_candidates*.csv")
    historical_df = combine_and_dedupe(historical_df)

    preference_weights = build_preference_weights(historical_df)

    if preference_weights:
        print(f"Loaded {len(preference_weights)} learned preference weights.")
    else:
        print("Not enough feedback yet. Using base scoring only.")

    existing_item_ids = set()
    if not historical_df.empty and "item_id" in historical_df.columns:
        existing_item_ids = set(historical_df["item_id"].astype(str))

    new_rows = []

    if not args.skip_search:
        for term in SEARCH_TERMS:
            print(f"Searching: {term}")
            items = search_ebay(term, limit=args.limit)

            for item in items:
                item_id = str(item.get("itemId", ""))

                if not item_id or item_id in existing_item_ids:
                    continue

                base_score, score_reasons = score_listing(item)
                preference_score, learned_reasons = preference_score_listing(item, preference_weights)
                final_score = base_score + preference_score

                image_url = item.get("image", {}).get("imageUrl")

                new_rows.append({
                    "my_score": "",
                    "final_score": final_score,
                    "title": item.get("title"),
                    "price": item.get("price", {}).get("value"),
                    "shipping_cost": extract_shipping_cost(item),
                    "total_cost": float(item.get("price", {}).get("value", 0) or 0) + extract_shipping_cost(item),
                    "image_url": image_url,
                    "item_url": item.get("itemWebUrl"),
                    "base_score": base_score,
                    "preference_score": preference_score,
                    "seller": item.get("seller", {}).get("username"),
                    "search_term": term,
                    "score_reasons": score_reasons,
                    "learned_reasons": learned_reasons,
                    "currency": item.get("price", {}).get("currency"),
                    "condition": item.get("condition"),
                    "item_id": item_id,
                    "date_pulled": datetime.now(timezone.utc).isoformat(),
                    "date_pulled_day": run_date,
                })

                existing_item_ids.add(item_id)

    new_df = pd.DataFrame(new_rows)

    combined_df = pd.concat([historical_df, new_df], ignore_index=True)
    combined_df = combine_and_dedupe(combined_df)

    if combined_df.empty:
        print("No candidates found.")
        return

    combined_df = ensure_columns(combined_df)
    combined_df = combined_df.sort_values(by="final_score", ascending=False)

    combined_df.to_csv(MASTER_CSV, index=False)

    report_df = filter_by_date(combined_df, args, run_date)
    report_df = ensure_columns(report_df)
    report_df = report_df.sort_values(by="final_score", ascending=False)

    report_df.to_csv(daily_csv, index=False)

    if args.date:
        report_title = f"Jewelry Deal Finder Daily Report - {args.date}"
    elif args.start_date or args.end_date:
        report_title = f"Jewelry Deal Finder Report - {args.start_date or 'start'} to {args.end_date or run_date}"
    else:
        report_title = f"Jewelry Deal Finder Daily Report - {run_date}"

    generate_html_report(report_df, daily_html, report_title)

    print(f"Added {len(new_df)} new candidates.")
    print(f"Saved master CSV: {MASTER_CSV}")
    print(f"Saved report CSV: {daily_csv}")
    print(f"Saved HTML report: {daily_html}")

    preview_cols = ["final_score", "my_score", "title", "price", "seller", "date_pulled_day"]
    print(report_df[preview_cols].head(10))


if __name__ == "__main__":
    main()