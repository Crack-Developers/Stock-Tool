from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
from functools import lru_cache

app = Flask(__name__)
CORS(app)  # Allow all origins for development

# -------- Load tickers --------
TICKER_PATH = os.path.join(os.path.dirname(__file__), "symbols", "tickers.csv")
if not os.path.exists(TICKER_PATH):
    raise FileNotFoundError(f"Tickers file not found at {TICKER_PATH}")

TICKER_DF = pd.read_csv(TICKER_PATH)
TICKER_DF["symbol"] = TICKER_DF["symbol"].astype(str)
TICKER_DF["name"] = TICKER_DF["name"].astype(str).str.lower()


def get_symbol_from_input(inp):
    """Accept either symbol or company name fragment and return a valid ticker."""
    if not inp:
        return None
    s = str(inp).strip()
    if s.upper() in set(TICKER_DF["symbol"].values):
        return s.upper()
    match = TICKER_DF[TICKER_DF["name"].str.contains(s.lower(), case=False, na=False)]
    if not match.empty:
        return match.iloc[0]["symbol"]
    return None


@lru_cache(maxsize=256)
def fetch_history_safe(ticker: str, start_str: str, end_str: str, interval: str = "1d"):
    """
    Fetch price history + reliable summary info (fast_info) for given ticker.
    """
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        end_inclusive = end + timedelta(days=1)

        print(f"[INFO] Fetching {ticker} from {start.date()} to {end.date()}")

        t = yf.Ticker(ticker)

        # Fetch price history
        df = t.history(start=start, end=end_inclusive, interval=interval)
        if df.empty:
            print(f"[WARN] Empty data for {ticker} – fallback to 1mo period")
            df = t.history(period="1mo", interval=interval)

        if df.empty:
            print(f"[ERROR] {ticker}: No data found after fallback")
            return None

        df.reset_index(inplace=True)
        if "Date" not in df.columns:
            df.rename(columns={df.columns[0]: "Date"}, inplace=True)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        records = df[["Date", "Close"]].to_dict(orient="records")

        # ✅ Reliable and fast stock info
        info = {}
        try:
            info = t.fast_info
        except Exception:
            print(f"[WARN] Could not fetch fast_info for {ticker}")

        # Helper
        def safe_get(key):
            val = info.get(key)
            if val is None or str(val).lower() in ["nan", "none"]:
                return None
            return val

        current_price = safe_get("last_price") or float(records[-1]["Close"])
        open_price = safe_get("open")
        high_price = safe_get("day_high")
        low_price = safe_get("day_low")
        prev_close = safe_get("previous_close")
        avg_vol = safe_get("ten_day_average_volume")
        mkt_cap = safe_get("market_cap")
        wk_high = safe_get("year_high")
        wk_low = safe_get("year_low")
        volume = safe_get("last_volume")

        summary = {
            "Open": open_price,
            "High": high_price,
            "Low": low_price,
            "PrevClose": prev_close,
            "Vol": volume,
            "AvgVol": avg_vol,
            "52wHigh": wk_high,
            "52wLow": wk_low,
            "MktCap": mkt_cap,
        }

        return {
            "records": records,
            "current": current_price,
            "summary": summary
        }

    except Exception as e:
        print(f"[EXCEPTION] fetch_history_safe({ticker}): {e}")
        return None


@app.route("/api/data", methods=["POST"])
def get_data():
    """
    Fetch stock history and summary info for selected tickers.
    """
    try:
        payload = request.get_json(force=True)
        tickers = payload.get("tickers", [])
        start = payload.get("start")
        end = payload.get("end")

        if not tickers or not start or not end:
            return jsonify({"error": "Missing tickers or date range"}), 400

        result = {}
        for t in tickers:
            symbol = get_symbol_from_input(t)
            if not symbol:
                result[t] = {"error": "Company/ticker not found"}
                continue

            fetched = fetch_history_safe(symbol, start, end)
            if not fetched:
                result[symbol] = {"error": "No data available for given range"}
                continue

            result[symbol] = {
                "symbol": symbol,
                "data": fetched["records"],
                "current": fetched["current"],
                "summary": fetched["summary"],
            }

        return jsonify({"start": start, "end": end, "data": result})

    except Exception as e:
        print("SERVER ERROR:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/api/tickers", methods=["GET"])
def tickers():
    """Return available tickers."""
    return jsonify(TICKER_DF.to_dict(orient="records"))


@app.route("/")
def home():
    return "✅ Backend running — Use /api/data or /api/tickers endpoints."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
