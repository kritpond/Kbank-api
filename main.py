import os
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import requests
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()

# Mock KBank endpoints are disabled unless explicitly enabled for UAT.
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


def validate_bank_request(payload, expected_function):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")
    if payload.get("functionName") != expected_function:
        raise HTTPException(status_code=400, detail="Invalid functionName")
    for field in ("transactionId", "transactionDateTime", "billerId", "terminalNo", "reference1", "tranAmount"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise HTTPException(status_code=400, detail=f"Missing or invalid {field}")
    try:
        timestamp = datetime.fromisoformat(payload["transactionDateTime"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Timezone is required")
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail="transactionDateTime must be ISO 8601 with timezone, e.g. 2026-11-11T10:34:01.352+07:00",
        )


def test_error(payload):
    if payload.get("billerId") != TEST_BILLER_ID:
        return "0001", "Invalid Payment reference number"
    if (
        payload.get("reference1") != TEST_REFERENCE1
        or payload.get("reference2", "") != TEST_REFERENCE2
    ):
        return "0001", "Invalid Payment reference number"
    if payload.get("tranAmount") != TEST_AMOUNT:
        return "0004", "Invalid payment amount"
    return None


def new_biller_transaction_id():
    return uuid4().hex[:20]


def inquiry_response(payload, code, description):
    result = {
        "functionName": "BillLookupResponse",
        "transactionId": payload["transactionId"],
        "transactionDateTime": now_bangkok(),
        "billerTransactionId": new_biller_transaction_id(),
        "responseCode": code,
        "responseDescription": description,
        "billerType": payload.get("billerType", ""),
        "billerId": payload["billerId"],
        "terminalNo": payload["terminalNo"],
        "promptPayTransactionId": payload.get("promptPayReferenceNumber", ""),
        "typeofReceiver": "",
        "reference1": payload["reference1"],
        "reference2": payload.get("reference2", ""),
        "reference3": payload.get("reference3", ""),
        "info1": "Test bill" if code == "0000" else "",
        "info2": "",
        "info3": "",
        "additional": {
            "rsAppId": "",
            "toBillerAccountName": "",
            "toBillerServiceName": "",
            "payerFee": "",
            "settlementDate": "",
            "receiverTaxID": "",
            "dueDate": "",
            "rtpReference": "",
        },
    }
    if code == "0000":
        result["tranAmount"] = payload["tranAmount"]
    return result


def payment_response(payload, code, description):
    return {
        "functionName": "BillPaymentResponse",
        "transactionId": payload["transactionId"],
        "responseDateTime": now_bangkok(),
        "billerTransactionId": new_biller_transaction_id(),
        "responseCode": code,
        "responseDescription": description,
        "terminalNo": payload["terminalNo"],
        "promptPayTransactionId": payload.get("promptPayReferenceNumber", ""),
        "additional": {"rsAppId": "", "settlementDate": ""},
    }


@app.get("/")
def read_root():
    return {"status": "online", "bank_api_mode": BANK_API_MODE}


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
        raise HTTPException(status_code=503, detail="Bank UAT endpoints are disabled")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    validate_bank_request(payload, "BillLookup")

    error = test_error(payload)
    if error:
        return inquiry_response(payload, *error)

    reference = (payload["reference1"], payload.get("reference2", ""))
    with _paid_references_lock:
        already_paid = reference in _paid_references
    if already_paid:
        return inquiry_response(payload, "0002", "Already paid")
    return inquiry_response(payload, "0000", "Success")


@app.post("/payment")
async def bill_payment(request: Request):
    if BANK_API_MODE != "uat":
        raise HTTPException(status_code=503, detail="Bank UAT endpoints are disabled")
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    validate_bank_request(payload, "BillPayment")

    error = test_error(payload)
    if error:
        return payment_response(payload, *error)

    reference = (payload["reference1"], payload.get("reference2", ""))
    with _paid_references_lock:
        _paid_references.add(reference)
    return payment_response(payload, "0000", "Success")
