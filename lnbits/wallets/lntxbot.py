import trio  # type: ignore
import httpx
from os import getenv
from typing import Optional, Dict, AsyncGenerator

from .base import InvoiceResponse, PaymentResponse, PaymentStatus, Wallet


class LntxbotWallet(Wallet):
    """https://github.com/fiatjaf/lntxbot/blob/master/api.go"""

    def __init__(self):
        endpoint = getenv("LNTXBOT_API_ENDPOINT")
        self.endpoint = endpoint[:-1] if endpoint.endswith("/") else endpoint

        key = getenv("LNTXBOT_KEY") or getenv("LNTXBOT_ADMIN_KEY") or getenv("LNTXBOT_INVOICE_KEY")
        self.auth = {"Authorization": f"Basic {key}"}

    def create_invoice(
        self, amount: int, memo: Optional[str] = None, description_hash: Optional[bytes] = None
    ) -> InvoiceResponse:
        data: Dict = {"amt": str(amount)}
        if description_hash:
            data["description_hash"] = description_hash.hex()
        else:
            data["memo"] = memo or ""

        r = httpx.post(
            url=f"{self.endpoint}/addinvoice",
            headers=self.auth,
            json=data,
        )

        if r.is_error:
            try:
                data = r.json()
                error_message = data["message"]
            except:
                error_message = r.text
                pass

            return InvoiceResponse(False, None, None, error_message)

        data = r.json()
        return InvoiceResponse(True, data["payment_hash"], data["pay_req"], None)

    def pay_invoice(self, bolt11: str) -> PaymentResponse:
        r = httpx.post(url=f"{self.endpoint}/payinvoice", headers=self.auth, json={"invoice": bolt11})

        if r.is_error:
            try:
                data = r.json()
                error_message = data["message"]
            except:
                error_message = r.text
                pass

            return PaymentResponse(False, None, 0, error_message)

        data = r.json()
        return PaymentResponse(True, data["decoded"]["payment_hash"], data["fee_msat"], None)

    def get_invoice_status(self, checking_id: str) -> PaymentStatus:
        r = httpx.post(url=f"{self.endpoint}/invoicestatus/{checking_id}?wait=false", headers=self.auth)

        data = r.json()
        if r.is_error or "error" in data:
            return PaymentStatus(None)

        if "preimage" not in data:
            return PaymentStatus(False)

        return PaymentStatus(True)

    def get_payment_status(self, checking_id: str) -> PaymentStatus:
        r = httpx.post(url=f"{self.endpoint}/paymentstatus/{checking_id}", headers=self.auth)

        data = r.json()
        if r.is_error or "error" in data:
            return PaymentStatus(None)

        statuses = {"complete": True, "failed": False, "pending": None, "unknown": None}
        return PaymentStatus(statuses[data.get("status", "unknown")])

    async def paid_invoices_stream(self) -> AsyncGenerator[str, None]:
        print("lntxbot does not support paid invoices stream yet")
        await trio.sleep(5)
        yield ""
