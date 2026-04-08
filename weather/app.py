import io
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import requests
import seaborn as sns
from boto3.dynamodb.conditions import Key

matplotlib.use("Agg")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# --- CONFIGURATION ---
METEO_URL = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current=temperature_2m,wind_speed_10m"
REGION_ID = "Central-VA"
TABLE_NAME   = os.environ.get("DYNAMODB_TABLE", "dp2-tracking")
S3_BUCKET    = os.environ["S3_BUCKET"]
AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")



def fetch_weather_data():
    """Fetch current temperature and wind speed."""
    try:
        resp = requests.get(METEO_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        
        current = data.get("current", {})
        temp = current.get("temperature_2m", 0)
        wind = current.get("wind_speed_10m", 0)
        
        log.info(f"Weather Station {REGION_ID}: {temp}°C, Wind: {wind}km/h")
        
        return {
            "region_d": REGION_ID,          
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "temp_celsius": Decimal(str(temp)), 
            "wind_speed": Decimal(str(wind)),
            "temp": int(temp)       
        }
    except Exception as e:
        log.error(f"Weather data fetch failed: {e}")
        return None

# ---------------------------------------------------------------------------
# Step 2 — Fetch History & Generate Artifacts (CSV + Plot)
# ---------------------------------------------------------------------------
def fetch_history(table) -> pd.DataFrame:
    items, kwargs = [], dict(
        KeyConditionExpression=Key("region_id").eq(REGION_ID),
        ScanIndexForward=True,
    )
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if not items:
        return pd.DataFrame()

    df = pd.DataFrame(items)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["temp"] = df["temp"].astype(int)
    return df.sort_values("timestamp").reset_index(drop=True)

def generate_plot(df: pd.DataFrame) -> io.BytesIO | None:
    if df.empty or len(df) < 2:
        return None

    sns.set_theme(style="darkgrid")
    fig, ax = plt.subplots(figsize=(12, 6))
    
    sns.lineplot(data=df, x="timestamp", y="temp", ax=ax, marker='o', color='#1E88E5')
    
    ax.set_title(f"Regional Weather Activity: {REGION_ID}", fontweight='bold')
    ax.set_ylabel("Temperature")
    ax.set_xlabel("Time (UTC)")
    
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    buf.seek(0)
    plt.close(fig)
    return buf

# ---------------------------------------------------------------------------
# Step 3 — Upload to S3 (PNG, CSV, and Index)
# ---------------------------------------------------------------------------
def upload_to_s3(plot_buf, df):
    s3 = boto3.client("s3", region_name=AWS_REGION)
    
    # 1. Upload Plot
    if plot_buf:
        s3.put_object(Bucket=S3_BUCKET, Key="plot.png", Body=plot_buf.getvalue(), ContentType="image/png")
    
    # 2. Upload CSV
    csv_buf = io.StringIO()
    df.to_csv(csv_buf, index=False)
    s3.put_object(Bucket=S3_BUCKET, Key="data.csv", Body=csv_buf.getvalue(), ContentType="text/csv")
    
    # 3. Upload/Update Index.html to show the new plot
    html = f"""
    <html><body style="background:#f0f0f0; font-family:sans-serif; text-align:center;">
        <h1>Live Flight Tracker: {REGION_ID}</h1>
        <img src="plot.png?t={int(datetime.now().timestamp())}" style="max-width:90%; border:1px solid #ccc;">
        <p><a href="data.csv">Download raw data.csv</a></p>
        <p>Last updated: {datetime.now(timezone.utc)}</p>
    </body></html>
    """
    s3.put_object(Bucket=S3_BUCKET, Key="index.html", Body=html, ContentType="text/html")

# ---------------------------------------------------------------------------
# Main Execution
# ---------------------------------------------------------------------------
def main():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TABLE_NAME)

    # 1. Ingest Weather
    weather_entry = fetch_weather_data()
    if weather_entry:
        table.put_item(Item=weather_entry)
        log.info(f"Successfully recorded weather for {REGION_ID}")

        # 2. Process & Publish
        history_df = fetch_history(table)
        if not history_df.empty:
            plot_buf = generate_plot(history_df)
            upload_to_s3(plot_buf, history_df)

if __name__ == "__main__":
    main()