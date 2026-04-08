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
OPENSKY_URL  = "https://opensky-network.org/api/states/all"
REGION_ID    = "Central-VA"  
TABLE_NAME   = os.environ.get("DYNAMODB_TABLE", "flight-tracking")
S3_BUCKET    = os.environ["S3_BUCKET"]
AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")


# Bounding Box for Central Virginia (lamin, lomin, lamax, lomax)
BOUNDS = {'lamin': 37.7, 'lomin': -78.8, 'lamax': 38.3, 'lomax': -78.2}

# ---------------------------------------------------------------------------
# Step 1 — Fetch Regional Flight Data
# ---------------------------------------------------------------------------

'''def get_opensky_token():
    auth_url = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": os.environ["OPENSKY_ID"],
        "client_secret": os.environ["OPENSKY_SECRET"]
    }
    response = requests.post(auth_url, data=data, timeout=10)
    response.raise_for_status()
    return response.json().get("access_token")'''

def fetch_flight_data():
    """Fetch current aircraft in bounds and return a summary for DynamoDB."""
    try:
        resp = requests.get(OPENSKY_URL, params=BOUNDS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        states = data.get("states")
        count = len(states) if states else 0
        return {
            "region_d": REGION_ID, # Matches your 'region_d' table key
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "flight_count": count
        }
    except Exception as e:
        log.error(f"Fetch failed: {e}")
        return None
    
'''def fetch_flight_data() -> dict:
    """Fetch current aircraft in bounds and return a summary for DynamoDB."""
    # Note: If you have an API key, use auth=(user, pass) in requests.get
    token = get_opensky_token()
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(OPENSKY_URL, params=BOUNDS, headers=headers, timeout=(5,20))
    resp.raise_for_status()
    data = resp.json()
    
    states = data.get("states")
    count = len(states) if states else 0
    
    return {
        "region_id": REGION_ID,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "flight_count": count,
        "unix_time": int(datetime.now(timezone.utc).timestamp())
    }'''

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
    df["flight_count"] = df["flight_count"].astype(int)
    return df.sort_values("timestamp").reset_index(drop=True)

def generate_plot(df: pd.DataFrame) -> io.BytesIO | None:
    if df.empty or len(df) < 2:
        return None

    sns.set_theme(style="darkgrid")
    fig, ax = plt.subplots(figsize=(12, 6))
    
    sns.lineplot(data=df, x="timestamp", y="flight_count", ax=ax, marker='o', color='#1E88E5')
    
    ax.set_title(f"Regional Air Traffic Activity: {REGION_ID}", fontweight='bold')
    ax.set_ylabel("Number of Aircraft in Airspace")
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

    # Ingest
    entry = fetch_flight_data()
    table.put_item(Item=entry)
    log.info(f"Recorded {entry['flight_count']} flights for {REGION_ID}")

    # Process & Publish
    history_df = fetch_history(table)
    plot_buf = generate_plot(history_df)
    upload_to_s3(plot_buf, history_df)

if __name__ == "__main__":
    main()