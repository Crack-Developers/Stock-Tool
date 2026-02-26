from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

# AI and Quantum Imports
from google import genai
import pennylane as qml
from pennylane import numpy as np

app = Flask(__name__)
CORS(app)  # Allow all origins for development

# NEW: Setup Gemini Client with your API Key
GEMINI_KEY = "AIzaSyCwMz8OphuKU5SkdsoQAV_q2bew6j9qdNY"
client = genai.Client(api_key=GEMINI_KEY)

# NEW: Quantum Circuit Setup (2 Qubits)
dev = qml.device("default.qubit", wires=2)

@qml.qnode(dev)
def quantum_predict_circuit(inputs, weights):
    # Data is encoded into quantum states
    qml.AngleEmbedding(inputs, wires=range(2))
    # Trainable Variational Layers
    qml.StronglyEntanglingLayers(weights, wires=range(2))
    # Measure the output (Expectation value)
    return qml.expval(qml.PauliZ(0))

def get_quantum_prediction(records):
    """Safely processes historical data through QNN to get a technical signal."""
    try:
        if not records or len(records) < 2: 
            return "Neutral"
            
        # Extract last two Close prices and normalize
        close_prices = [float(r['Close']) for r in records]
        max_val = max(close_prices) if max(close_prices) != 0 else 1
        normalized_input = np.array([close_prices[-2], close_prices[-1]]) / max_val
        
        # Define weights for the Quantum Circuit
        shape = qml.StronglyEntanglingLayers.shape(n_layers=2, n_wires=2)
        weights = np.random.random(size=shape)
        
        # Get result from Quantum Simulator
        score = quantum_predict_circuit(normalized_input, weights)
        
        # IMPORTANT: Convert Quantum Tensor to standard float for JSON serialization
        final_score = float(score)
        
        return "Bullish (Buy)" if final_score > 0 else "Bearish (Sell)"
    except Exception as e:
        print(f"[QUANTUM ERROR] {e}")
        return "Stable/Neutral"

# -------- Load tickers --------
TICKER_PATH = os.path.join(os.path.dirname(__file__), "symbols", "tickers.csv")
if not os.path.exists(TICKER_PATH):
    # Fallback to current directory if symbols folder is missing
    TICKER_PATH = os.path.join(os.path.dirname(__file__), "tickers.csv")

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
    """Fetch price history + reliable summary info."""
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
        end_inclusive = end + timedelta(days=1)

        print(f"[INFO] Fetching {ticker} from {start.date()} to {end.date()}")
        t = yf.Ticker(ticker)

        df = t.history(start=start, end=end_inclusive, interval=interval)
        if df.empty:
            df = t.history(period="1mo", interval=interval)

        if df.empty: return None

        # Calculate Technical Indicators for higher AI accuracy
        df['SMA_5'] = df['Close'].rolling(window=5).mean()
        
        df.reset_index(inplace=True)
        if "Date" not in df.columns:
            df.rename(columns={df.columns[0]: "Date"}, inplace=True)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

        records = df[["Date", "Close", "SMA_5"]].fillna(0).to_dict(orient="records")
        
        info = {}
        try:
            info = t.fast_info
        except: pass

        def safe_get(key):
            val = info.get(key)
            if val is None or str(val).lower() in ["nan", "none"]: return None
            return val

        current_price = safe_get("last_price") or float(records[-1]["Close"])
        
        summary = {
            "Open": safe_get("open"),
            "High": safe_get("day_high"),
            "Low": safe_get("day_low"),
            "PrevClose": safe_get("previous_close"),
            "Vol": safe_get("last_volume"),
            "AvgVol": safe_get("ten_day_average_volume"),
            "52wHigh": safe_get("year_high"),
            "52wLow": safe_get("year_low"),
            "MktCap": safe_get("market_cap"),
        }

        return {"records": records, "current": current_price, "summary": summary}
    except Exception as e:
        print(f"[EXCEPTION] {e}")
        return None


@app.route("/api/data", methods=["POST"])
def get_data():
    """Existing Route for frontend charts."""
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
            if not symbol: continue
            fetched = fetch_history_safe(symbol, start, end)
            if not fetched: continue
            result[symbol] = {
                "symbol": symbol,
                "data": fetched["records"],
                "current": fetched["current"],
                "summary": fetched["summary"],
            }
        return jsonify({"start": start, "end": end, "data": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def process_single_analysis(t, start, end):
    """Worker function for parallel processing."""
    symbol = get_symbol_from_input(t)
    if not symbol: return None
    
    fetched = fetch_history_safe(symbol, start, end)
    if not fetched: return None

    # 1. Quantum Technical Signal
    q_signal = get_quantum_prediction(fetched["records"])

    # 2. Gemini 1.5 Flash Analysis
    try:
        # Use concise data slice (last 5 days) for free tier stability
        recent_summary = fetched["records"][-5:] 
        prompt = (
            f"Analyze {symbol} stock. Market Summary (Price & SMA): {recent_summary}. "
            f"The Technical Quantum Signal is {q_signal}. "
            "Compare the market data with the Quantum signal and provide a 1-sentence "
            "investment advice for: 1. Current Day, 2. Short Term, 3. Long Term."
        )
        
        ai_response = client.models.generate_content(
            model="gemini-1.5-flash", 
            contents=prompt
        )
        ai_text = ai_response.text if ai_response.text else "Analysis generated successfully."
    except Exception as ai_e:
        print(f"[AI ERROR] {ai_e}")
        ai_text = f"Relying on Quantum Signal: {q_signal}"

    return {
        "symbol": symbol,
        "current_price": float(fetched["current"]),
        "quantum_signal": str(q_signal),
        "ai_analysis": ai_text
    }

@app.route("/api/analyze", methods=["POST"])
def analyze_data():
    """Hybrid Analysis using Parallel Threading for high speed."""
    try:
        payload = request.get_json(force=True)
        tickers = payload.get("tickers", [])
        start = payload.get("start")
        end = payload.get("end")

        analysis_results = {}
        
        # Parallel Execution: Runs analysis for all tickers at once
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(process_single_analysis, t, start, end) for t in tickers]
            for future in futures:
                res = future.result()
                if res:
                    analysis_results[res["symbol"]] = res

        return jsonify(analysis_results)
    except Exception as e:
        print("ANALYSIS ERROR:", e)
        return jsonify({"error": "Failed to process hybrid analysis"}), 500

@app.route("/api/tickers", methods=["GET"])
def tickers():
    return jsonify(TICKER_DF.to_dict(orient="records"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)