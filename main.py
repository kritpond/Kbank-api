import os
import threading
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# Public mock endpoints are only enabled when explicitly configured for UAT.
BANK_API_MODE = os.getenv("BANK_API_MODE", "disabled").strip().lower()
TEST_BILLER_ID = os.getenv("BANK_TEST_BILLER_ID", "98499")
TEST_REFERENCE1 = os.getenv("BANK_TEST_REFERENCE1", "300000025751")
TEST_REFERENCE2 = os.getenv("BANK_TEST_REFERENCE2", "1733084")
TEST_AMOUNT = os.getenv("BANK_TEST_AMOUNT", "120.00")
_paid_references = set()
_paid_references_lock = threading.Lock()
BANGKOK_TZ = timezone(timedelta(hours=7))


def now_bangkok():
    return datetime.now(BANGKOK_TZ).isoformat(timespec="milliseconds")


def make_biller_transaction_id():
    return uuid4().hex[:20]


def uat_disabled():
    return JSONResponse(
        status_code=503,
        content={"error": "Bank UAT endpoints are disabled; set BANK_API_MODE=uat for sandbox testing only."},
    )


def lookup_response(data, code, description):
    response = {
        "functionName": "BillLookupResponse",
        "transactionId": str(data.get("transactionId", "")),
        "transactionDateTime": now_bangkok(),
        "billerTransactionId": make_biller_transaction_id(),
        "responseCode": code,
        "responseDescription": description,
        "billerType": str(data.get("billerType", "")),
        "billerId": str(data.get("billerId", "")),
        "terminalNo": str(data.get("terminalNo", "")),
        "promptPayTransactionId": str(data.get("promptPayReferenceNumber", "")),
        "reference1": str(data.get("reference1", "")),
        "reference2": str(data.get("reference2", "")),
        "reference3": str(data.get("reference3", "")),
    }
    if code == "0000":
        response.update({"tranAmount": str(data.get("tranAmount", "")), "info1": "Test bill"})
    response["additional"] = {
        "rsAppId": "",
        "toBillerAccountName": "",
        "toBillerServiceName": "",
        "payerFee": "",
        "settlementDate": "",
        "receiverTaxID": "",
        "dueDate": str(data.get("dueDate", "")),
        "rtpReference": str(data.get("rtpReference", "")),
    }
    return response


def payment_response(data, code, description):
    return {
        "functionName": "BillPaymentResponse",
        "transactionId": str(data.get("transactionId", "")),
        "responseDateTime": now_bangkok(),
        "billerTransactionId": make_biller_transaction_id(),
        "responseCode": code,
        "responseDescription": description,
        "terminalNo": str(data.get("terminalNo", "")),
        "promptPayTransactionId": str(data.get("promptPayReferenceNumber", "")),
        "additional": {"rsAppId": "", "settlementDate": ""},
    }


def validate_test_bill(data):
    if str(data.get("billerId", "")) != TEST_BILLER_ID:
        return "0001", "Invalid Payment reference number"
    if (
        str(data.get("reference1", "")) != TEST_REFERENCE1
        or str(data.get("reference2", "")) != TEST_REFERENCE2
    ):
        return "0001", "Invalid Payment reference number"
    try:
        if format(float(data.get("tranAmount", "")), ".2f") != format(float(TEST_AMOUNT), ".2f"):
            return "0004", "Invalid payment amount"
    except (TypeError, ValueError):
        return "0004", "Invalid payment amount"
    return None


async def read_json_request(request: Request):
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


@app.get("/")
def read_root():
    return {"status": "online", "mode": BANK_API_MODE}


@app.get("/my-ip")
def get_ip():
    try:
        response = requests.get("https://api.ipify.org?format=json", timeout=5)
        response.raise_for_status()
        return {"outbound_ip": response.json().get("ip")}
    except requests.RequestException:
        return {"error": "Could not determine outbound IP"}


@app.post("/inquiry")
async def bill_lookup(request: Request):
    if BANK_API_MODE != "uat":
        return uat_disabled()
    data = await read_json_request(request)
    if data is None:
        return JSONResponse(status_code=400, content={"error": "Expected a JSON object"})

    # Reject malformed timestamps, but do not require a fixed clock window: bank test
    # exercises may use historical fixture timestamps. Response time is generated now.
    timestamp = data.get("transactionDateTime")
    try:
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid transactionDateTime; use ISO 8601 with timezone"})

    error = validate_test_bill(data)
    if error:
        return lookup_response(data, *error)
    reference = (str(data.get("reference1", "")), str(data.get("reference2", "")))
    with _paid_references_lock:
        already_paid = reference in _paid_references
    if already_paid:
        return lookup_response(data, "0002", "Already paid")
    return lookup_response(data, "0000", "Success")


@app.post("/payment")
async def bill_payment(request: Request):
    if BANK_API_MODE != "uat":
        return uat_disabled()
    data = await read_json_request(request)
    if data is None:
        return JSONResponse(status_code=400, content={"error": "Expected a JSON object"})

    timestamp = data.get("transactionDateTime")
    try:
        if not isinstance(timestamp, str) or not timestamp.strip():
            raise ValueError
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Invalid transactionDateTime; use ISO 8601 with timezone"})

    error = validate_test_bill(data)
    if error:
        return payment_response(data, *error)
    reference = (str(data.get("reference1", "")), str(data.get("reference2", "")))
    with _paid_references_lock:
        _paid_references.add(reference)
    return payment_response(data, "0000", "Success")
