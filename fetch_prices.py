#!/usr/bin/env python3
"""
fetch_prices.py
Fetches the two most recent EOD closing prices for SaaS tracker tickers.
Prints JSON so Claude can read it directly before updating saas_ranking.html.

Usage:
    python fetch_prices.py
    python fetch_prices.py --date 2026-04-16   # verify a specific date
"""

import json
import sys
import argparse
import re
from datetime import datetime

try:
    import yfinance as yf
except Exception:
    yf = None

TICKERS = ["INTU", "ADSK", "HUBS", "CRM", "DDOG", "SNOW", "VEEV", "NOW", "TYL"]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format (default: most recent trading day)",
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

    return args


def history_to_valid_pairs(history_df):
    if history_df is None or history_df.empty or "Close" not in history_df:
        return []

    valid = []
    for idx, close in history_df["Close"].dropna().items():
        # yfinance returns a pandas.Timestamp index; keep dates in YYYY-MM-DD.
        date_str = idx.strftime("%Y-%m-%d")
        valid.append((date_str, round(float(close), 2)))
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


def fetch_prices(target_date: str = None):
    if yf is None:
        print(
            json.dumps(
                {
                    "prices": {},
                    "errors": [
                        "yfinance is not installed. Install it with: pip install yfinance"
                    ],
                },
                indent=2,
            )
        )
        sys.exit(1)

    prices = {}
    errors = []

    for ticker in TICKERS:
        try:
            period = "1mo" if target_date else "5d"
            history = yf.Ticker(ticker).history(
                period=period,
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
            valid = history_to_valid_pairs(history)

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
    fetch_prices(args.date)