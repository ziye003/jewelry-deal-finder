珠宝捡漏小手办

# Cyber gold digger

A personal jewelry sourcing assistant for finding potentially underpriced vintage, estate, and solid gold jewelry listings on eBay.

## Current Status

- eBay Developer account created
- Production keyset exemption granted for Marketplace Account Deletion notifications
- Production OAuth token works
- Basic eBay Browse API search works
- First scoring function created
- Current output: `ebay_candidates.csv`

## Setup

Create a `.env` file:

```env
EBAY_CLIENT_ID=your_production_client_id
EBAY_CLIENT_SECRET=your_production_client_secret
