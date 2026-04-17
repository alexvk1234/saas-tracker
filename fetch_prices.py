#!/usr/bin/env python3
"""
fetch_prices.py
Fetches the two most recent EOD closing prices for SaaS tracker tickers.
Prints JSON so Claude can read it directly before updating saas_ranking.html.

Usage:
    python fetch_prices.py
    python fetch_prices.py --date 2026-04-16   # verify a specific date
"""

import urllib.request
import urllib.error
import json
import sys
import argparse
import ssl
import importlib
from datetime import datetime, timezone

try:
    certifi = importlib.import_module("certifi")
except Exception:
    certifi = None

TICKERS = ["INTU", "ADSK", "HUBS", "CRM", "DDOG", "SNOW", "VEEV", "NOW", "TYL"]


def build_ssl_context():
    # Prefer certifi's CA bundle to avoid macOS trust-store issues in some Python installs.
    if certifi is not None:
        return ssl.create_default_context(cafile=certifi.where())
    return ssl.create_default_context()


SSL_CONTEXT = build_ssl_context()
INSECURE_SSL_CONTEXT = ssl._create_unverified_context()


def load_json(req, timeout=10):
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=SSL_CONTEXT) as r:
            return json.load(r), False
    except Exception as e:
        reason = getattr(e, "reason", None)
        is_cert_error = (
            isinstance(e, ssl.SSLCertVerificationError)
            or isinstance(reason, ssl.SSLCertVerificationError)
            or "CERTIFICATE_VERIFY_FAILED" in str(e)
        )

        # Fallback only for missing/invalid CA chains on local Python installs.
        if is_cert_error:
            with urllib.request.urlopen(req, timeout=timeout, context=INSECURE_SSL_CONTEXT) as r:
                return json.load(r), True
        raise

def fetch_prices(target_date: str = None):
    prices = {}
    errors = []
    warnings = []
    used_insecure_ssl = False

    for ticker in TICKERS:
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
            f"?interval=1d&range=10d"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; price-fetcher/1.0)"}
        )

        try:
            data, insecure_used = load_json(req, timeout=10)
            used_insecure_ssl = used_insecure_ssl or insecure_used

            result = data["chart"]["result"][0]
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]

            # Pair timestamps with closes, drop nulls (e.g. half-trading days)
            valid = [
                (datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"), round(c, 2))
                for t, c in zip(timestamps, closes)
                if c is not None
            ]

            if not valid or len(valid) < 2:
                errors.append(f"{ticker}: not enough data points")
                continue

            # If a target date is given, find that day and the day before it
            if target_date:
                dates = [d for d, _ in valid]
                if target_date not in dates:
                    errors.append(f"{ticker}: date {target_date} not found in {dates}")
                    continue
                idx = dates.index(target_date)
                if idx == 0:
                    errors.append(f"{ticker}: no prior-day data before {target_date}")
                    continue
                prev_date, prev_close = valid[idx - 1]
                curr_date, curr_close = valid[idx]
            else:
                prev_date, prev_close = valid[-2]
                curr_date, curr_close = valid[-1]

            change = round(curr_close - prev_close, 2)
            change_pct = round((change / prev_close) * 100, 2)

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
    if used_insecure_ssl:
        warnings.append(
            "Fell back to insecure SSL (certificate verification disabled). "
            "Install certifi in this environment to restore secure verification: pip install certifi"
        )
    if warnings:
        output["warnings"] = warnings
    if errors:
        output["errors"] = errors

    print(json.dumps(output, indent=2))

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        help="Target date in YYYY-MM-DD format (default: most recent trading day)",
        default=None,
    )
    args = parser.parse_args()
    fetch_prices(args.date)