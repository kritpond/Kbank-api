import requests
from fastapi import FastAPI

app = FastAPI()


@app.get("/")
def read_root():
    return {"status": "online"}


@app.get("/my-ip")
def get_ip():
    try:
        ip = requests.get("https://api.ipify.org?format=json", timeout=5).json()
        return {"outbound_ip": ip.get("ip")}
    except Exception as e:
        return {"error": str(e)}
