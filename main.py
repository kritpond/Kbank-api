import os
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

# These mock payment endpoints are disabled unless Railway sets BANK_API_MODE=uat.
BANK_UAT_ENABLED = os.getenv("BANK_API_MODE", "disabled").lower() == "uat"
TEST_BILLER_ID = os.getenv("BANK_TEST_BILLER_ID", "98499")
TEST_REFERENCE1 = os.getenv("BANK_TEST_REFERENCE1", "300000025751")
TEST_REFERENCE2 = os.getenv("BANK_TEST_REFERENCE2", "1733084")
TEST_AMOUNT = os.getenv("BANK_TEST_AMOUNT", "120.00")
_paid_references = set()
_paid_references_lock = threading.Lock()


def bangkok_timestamp():
    return datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="milliseconds")


def new_biller_transaction_id():
    return uuid4().hex[:20]


def inquiry_response(payload, code, description):
    return {
        "functionName": "BillLookupResponse",
        "transactionId": str(payload.get("transactionId", "")),
        "transactionDateTime": bangkok_timestamp(),
        "billerTransactionId": new_biller_transaction_id(),
        "responseCode": code,
        "responseDescription": description,
        "billerType": str(payload.get("billerType", "")),
        "billerId": str(payload.get("billerId", "")),
        "terminalNo": str(payload.get("terminalNo", "")),
        "promptPayTransactionId": str(payload.get("promptPayReferenceNumber", "")),
        "typeofReceiver": "",
        "reference1": str(payload.get("reference1", "")),
        "reference2": str(payload.get("reference2", "")),
        "reference3": str(payload.get("reference3", "")),
        "tranAmount": str(payload.get("tranAmount", "")) if code == "0000" else "",
        "info1": "Test bill",
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


def payment_response(payload, code, description):
    return {
        "functionName": "BillPaymentResponse",
        "transactionId": str(payload.get("transactionId", "")),
        "responseDateTime": bangkok_timestamp(),
        "billerTransactionId": new_biller_transaction_id(),
        "responseCode": code,
        "responseDescription": description,
        "terminalNo": str(payload.get("terminalNo", "")),
        "promptPayTransactionId": str(payload.get("promptPayReferenceNumber", "")),
        "additional": {"rsAppId": "", "settlementDate": ""},
    }


def test_case_error(payload):
    if str(payload.get("billerId", "")) != TEST_BILLER_ID:
        return "0001", "Invalid Payment reference number"
    if (
        str(payload.get("reference1", "")) != TEST_REFERENCE1
        or str(payload.get("reference2", "")) != TEST_REFERENCE2
    ):
        return "0001", "Invalid Payment reference number"
    if str(payload.get("tranAmount", "")) != TEST_AMOUNT:
        return "0004", "Invalid payment amount"
    return None


@app.get("/")
def read_root():
    return {"status": "online"}


@app.get("/my-ip")
def get_ip():
    try:
        ip = requests.get("https://api.ipify.org?format=json", timeout=5).json()
        return {"outbound_ip": ip.get("ip")}
    except Exception:
        return {"error": "Could not determine outbound IP"}


@app.post("/inquiry")
async def bill_lookup(request: Request):
    if not BANK_UAT_ENABLED:
        return JSONResponse(status_code=503, content={"error": "Bank UAT endpoints are disabled"})

    payload = await request.json()
    error = test_case_error(payload)
    if error:
        return inquiry_response(payload, *error)

    reference = (str(payload.get("reference1", "")), str(payload.get("reference2", "")))
    with _paid_references_lock:
        already_paid = reference in _paid_references
    if already_paid:
        return inquiry_response(payload, "0002", "Already paid")
    return inquiry_response(payload, "0000", "Success")


@app.post("/payment")
async def bill_payment(request: Request):
    if not BANK_UAT_ENABLED:
        return JSONResponse(status_code=503, content={"error": "Bank UAT endpoints are disabled"})

    payload = await request.json()
    error = test_case_error(payload)
    if error:
        return payment_response(payload, *error)

    reference = (str(payload.get("reference1", "")), str(payload.get("reference2", "")))
    with _paid_references_lock:
        _paid_references.add(reference)
    return payment_response(payload, "0000", "Success")
