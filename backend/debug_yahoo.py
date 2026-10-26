import sys
import yfinance as yf

print(f"yfinance version: {yf.__version__}")
print(f"python version: {sys.version}")
print("-" * 60)

try:
    df = yf.download("RELIANCE.NS", period="6mo", interval="1d",
                      auto_adjust=True, progress=False)
    print("SUCCESS - got", len(df), "rows")
    print(df.tail())
except Exception as e:
    print("FAILED with exception:")
    print(type(e).__name__, "-", e)
    import traceback
    traceback.print_exc()
