import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from customer_email_delivery import CustomerEmailReceiptDelivery


class CustomerEmailReceiptDeliveryTests(unittest.TestCase):
    def test_sends_fns_receipt_as_attachment(self):
        def handler(request):
            self.assertIn("/receipt/526228466371/receipt-1/print", str(request.url))
            return httpx.Response(200, content=b"%PDF-1.4 receipt")

        delivery = CustomerEmailReceiptDelivery(
            inn="526228466371",
            host="smtp.example.com",
            port=465,
            user="mailer@example.com",
            password="secret",
            use_tls=False,
            transport=httpx.MockTransport(handler),
        )
        smtp = MagicMock()
        smtp.__enter__.return_value = smtp
        with patch("customer_email_delivery.smtplib.SMTP_SSL", return_value=smtp):
            result = asyncio.run(delivery.deliver({
                "receipt_uuid": "receipt-1",
                "customer_email": "buyer@example.com",
                "amount": "690.00",
            }))

        self.assertEqual("delivered", result.status)
        message = smtp.send_message.call_args.args[0]
        self.assertEqual("buyer@example.com", message["To"])
        self.assertEqual("application/pdf", message.get_payload()[1].get_content_type())

    def test_rejects_missing_customer_email(self):
        delivery = CustomerEmailReceiptDelivery(
            inn="526228466371",
            host="smtp.example.com",
            port=465,
            user="mailer@example.com",
            password="secret",
        )
        result = asyncio.run(delivery.deliver({
            "receipt_uuid": "receipt-1",
            "amount": "690.00",
        }))
        self.assertEqual("undeliverable", result.status)


if __name__ == "__main__":
    unittest.main()
