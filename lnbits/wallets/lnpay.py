import json
import trio  # type: ignore
import httpx
from os import getenv
from http import HTTPStatus
from typing import Optional, Dict, AsyncGenerator
from quart import request

from .base import InvoiceResponse, PaymentResponse, PaymentStatus, Wallet


class LNPayWallet(Wallet):
    """https://docs.lnpay.co/"""

    def __init__(self):
        endpoint = getenv("LNPAY_API_ENDPOINT", "https://lnpay.co/v1")
        self.endpoint = endpoint[:-1] if endpoint.endswith("/") else endpoint
        self.wallet_key = getenv("LNPAY_WALLET_KEY") or getenv("LNPAY_ADMIN_KEY")
        self.auth = {"X-Api-Key": getenv("LNPAY_API_KEY")}

    def create_invoice(
        self,
        amount: int,
        memo: Optional[str] = None,
        description_hash: Optional[bytes] = None,
    ) -> InvoiceResponse:
        data: Dict = {"num_satoshis": f"{amount}"}
        if description_hash:
            data["description_hash"] = description_hash.hex()
        else:
            data["memo"] = memo or ""

        r = httpx.post(
            url=f"{self.endpoint}/user/wallet/{self.wallet_key}/invoice",
            headers=self.auth,
            json=data,
        )
        ok, checking_id, payment_request, error_message = (
            r.status_code == 201,
            None,
            None,
            r.text,
        )

        if ok:
            data = r.json()
            checking_id, payment_request = data["id"], data["payment_request"]

        return InvoiceResponse(ok, checking_id, payment_request, error_message)

    def pay_invoice(self, bolt11: str) -> PaymentResponse:
        r = httpx.post(
            url=f"{self.endpoint}/user/wallet/{self.wallet_key}/withdraw",
            headers=self.auth,
            json={"payment_request": bolt11},
        )
        ok, checking_id, fee_msat, error_message = r.status_code == 201, None, 0, None

        if ok:
            checking_id = r.json()["lnTx"]["id"]

        return PaymentResponse(ok, checking_id, fee_msat, error_message)

    def get_invoice_status(self, checking_id: str) -> PaymentStatus:
        return self.get_payment_status(checking_id)

    def get_payment_status(self, checking_id: str) -> PaymentStatus:
        r = httpx.get(
            url=f"{self.endpoint}/user/lntx/{checking_id}?fields=settled",
            headers=self.auth,
        )

        if r.is_error:
            return PaymentStatus(None)

        statuses = {0: None, 1: True, -1: False}
        return PaymentStatus(statuses[r.json()["settled"]])

    async def paid_invoices_stream(self) -> AsyncGenerator[str, None]:
        self.send, receive = trio.open_memory_channel(0)
        async for value in receive:
            yield value

    async def webhook_listener(self):
        text: str = await request.get_data()
        data = json.loads(text)
        if type(data) is not dict or "event" not in data or data["event"].get("name") != "wallet_receive":
            return "", HTTPStatus.NO_CONTENT

        lntx_id = data["data"]["wtx"]["lnTx"]["id"]
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.endpoint}/user/lntx/{lntx_id}?fields=settled",
                headers=self.auth,
            )
            data = r.json()
            if data["settled"]:
                await self.send.send(lntx_id)

        return "", HTTPStatus.NO_CONTENT
