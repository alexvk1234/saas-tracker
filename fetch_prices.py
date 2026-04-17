#!/usr/bin/env python3
"""
fetch_prices.py
Fetches the two most recent EOD closing prices for SaaS tracker tickers.
Prints JSON so Claude can read it directly before updating saas_ranking.html.

Usage:
    python fetch_prices.py
    python fetch_prices.py --date 2026-04-16   # verify a specific date
    python fetch_prices.py --api-key YOUR_ALPHA_VANTAGE_KEY
"""

import json
import sys
import argparse
import re
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import importlib
from datetime import datetime

try:
    certifi = importlib.import_module("certifi")
except Exception:
    certifi = None

TICKERS = ["INTU", "ADSK", "HUBS", "CRM", "DDOG", "SNOW", "VEEV", "NOW", "TYL"]
ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"
REQUEST_DELAY_SECONDS = 1.2


def build_ssl_context():
    # Prefer certifi's CA bundle to avoid local trust-store issues.
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


SSL_CONTEXT = build_ssl_context()


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format (default: most recent trading day)",
        default=None,
    )
    parser.add_argument(
        "--api-key",
        help=(
            "Alpha Vantage API key. If omitted, uses ALPHAVANTAGE_API_KEY "
            "or ALPHA_VANTAGE_API_KEY from the environment."
        ),
        default=None,
    )
    args = parser.parse_args()

    if args.date is not None:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date) is None:
            parser.error(f"Invalid --date '{args.date}'. Expected YYYY-MM-DD.")
        try:
            datetime.strptime(args.date, "%Y-%m-%d")
        except ValueError:
            parser.error(f"Invalid --date '{args.date}'. Expected YYYY-MM-DD.")

    api_key = (
        args.api_key
        or os.getenv("ALPHAVANTAGE_API_KEY")
        or os.getenv("ALPHA_VANTAGE_API_KEY")
    )
    if not api_key:
        parser.error(
            "Missing Alpha Vantage API key. Use --api-key or set ALPHAVANTAGE_API_KEY."
        )
    args.api_key = api_key.strip()

    return args


def load_json_with_retries(url, retries=3, timeout=20, rate_limit_sleep=15):
    last_error = None

    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; price-fetcher/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as response:
                payload = json.load(response)

            # Alpha Vantage sends rate-limit notices in successful HTTP responses.
            if isinstance(payload, dict) and payload.get("Note"):
                last_error = RuntimeError(payload["Note"])
                if attempt < retries:
                    time.sleep(rate_limit_sleep)
                    continue
                raise last_error

            return payload

        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError(f"Failed to fetch URL after retries: {last_error}")


def fetch_alpha_vantage_daily(ticker, api_key, outputsize):
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": ticker,
        "outputsize": outputsize,
        "apikey": api_key,
    }
    url = f"{ALPHAVANTAGE_URL}?{urllib.parse.urlencode(params)}"
    data = load_json_with_retries(url)

    if not isinstance(data, dict):
        raise ValueError("unexpected API response type")
    if data.get("Error Message"):
        raise ValueError(data["Error Message"])
    if data.get("Information"):
        raise ValueError(data["Information"])

    series = data.get("Time Series (Daily)")
    if not isinstance(series, dict) or not series:
        raise ValueError("missing Time Series (Daily) in API response")

    valid = []
    for date_str, values in series.items():
        try:
            close = round(float(values["4. close"]), 2)
            valid.append((date_str, close))
        except Exception:
            continue

    valid.sort(key=lambda item: item[0])
    return valid


def select_prev_curr(valid_pairs, target_date=None):
    if len(valid_pairs) < 2:
        raise ValueError("not enough data points")

    if target_date is None:
        return valid_pairs[-2], valid_pairs[-1]

    dates = [d for d, _ in valid_pairs]
    if target_date not in dates:
        raise ValueError(f"date {target_date} not found in {dates}")

    idx = dates.index(target_date)
    if idx == 0:
        raise ValueError(f"no prior-day data before {target_date}")

    return valid_pairs[idx - 1], valid_pairs[idx]


def fetch_prices(api_key: str, target_date: str = None):
    prices = {}
    errors = []

    for idx, ticker in enumerate(TICKERS):
        if idx > 0:
            time.sleep(REQUEST_DELAY_SECONDS)

        try:
            outputsize = "full" if target_date else "compact"
            valid = fetch_alpha_vantage_daily(
                ticker=ticker,
                api_key=api_key,
                outputsize=outputsize,
            )

            (prev_date, prev_close), (curr_date, curr_close) = select_prev_curr(
                valid,
                target_date=target_date,
            )

            change = round(curr_close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2) if prev_close != 0 else None

            prices[ticker] = {
                "prev_date":  prev_date,
                "prev_close": prev_close,
                "date":       curr_date,
                "close":      curr_close,
                "change":     change,
                "change_pct": change_pct,
                "direction":  "▲" if change >= 0 else "▼",
            }

        except Exception as e:
            errors.append(f"{ticker}: {e}")

    output = {"prices": prices}
    if errors:
        output["errors"] = errors

    print(json.dumps(output, indent=2))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    fetch_prices(args.api_key, args.date)