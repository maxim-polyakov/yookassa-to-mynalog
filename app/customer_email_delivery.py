import asyncio
import logging
import smtplib
from decimal import Decimal
from email.message import EmailMessage
from urllib.parse import quote

import httpx

from customer_receipt_delivery import DeliveryResult


class CustomerEmailReceiptDelivery:
    """Downloads the My Tax receipt and emails it to the payment customer."""

    def __init__(
        self,
        *,
        inn,
        host,
        port,
        user,
        password,
        from_email=None,
        from_name=None,
        use_tls=True,
        nalog_proxy=None,
        max_bytes=10 * 1024 * 1024,
        transport=None,
    ):
        self.inn = str(inn)
        self.host = host
        self.port = int(port)
        self.user = user
        self.password = password
        self.from_email = from_email or user
        self.from_name = from_name or "Kanban"
        self.use_tls = use_tls
        self.nalog_proxy = nalog_proxy
        self.max_bytes = max_bytes
        self.transport = transport

    def receipt_url(self, receipt_uuid):
        return (
            "https://lknpd.nalog.ru/api/v1/receipt/"
            f"{quote(self.inn, safe='')}/{quote(str(receipt_uuid).strip(), safe='')}/print"
        )

    async def deliver(self, job):
        email = str(job.get("customer_email") or "").strip()
        if "@" not in email:
            return DeliveryResult("undeliverable", error="email покупателя отсутствует")
        try:
            content, content_type, filename = await self._download(
                self.receipt_url(job["receipt_uuid"]),
                job["receipt_uuid"],
            )
            await asyncio.to_thread(
                self._send,
                email,
                job,
                content,
                content_type,
                filename,
            )
            logging.info("Чек %s отправлен на %s.", job["receipt_uuid"], email)
            return DeliveryResult("delivered")
        except smtplib.SMTPRecipientsRefused as exc:
            return DeliveryResult("undeliverable", error=self._safe_error(exc))
        except Exception as exc:
            return DeliveryResult("retry", error=self._safe_error(exc))

    async def _download(self, url, receipt_uuid):
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0),
            proxy=self.nalog_proxy,
            transport=self.transport,
            trust_env=self.transport is None,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
        content = response.content
        if len(content) > self.max_bytes:
            raise ValueError("файл чека превышает допустимый размер")
        content_type, extension = self._file_type(content)
        return content, content_type, f"receipt_{receipt_uuid}.{extension}"

    @staticmethod
    def _file_type(content):
        if content.startswith(b"%PDF-"):
            return "application/pdf", "pdf"
        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png", "png"
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg", "jpg"
        raise ValueError("ФНС вернула файл неизвестного формата")

    def _send(self, recipient, job, content, content_type, filename):
        amount = Decimal(str(job["amount"])).quantize(Decimal("0.01"))
        message = EmailMessage()
        message["Subject"] = "Чек по оплате подписки Kanban"
        message["From"] = f"{self.from_name} <{self.from_email}>"
        message["To"] = recipient
        message.set_content(
            "Ваш платёж зарегистрирован в ФНС через сервис «Мой налог».\n"
            f"Сумма: {amount:.2f} руб.\n"
            f"Ссылка на чек: {self.receipt_url(job['receipt_uuid'])}\n"
        )
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(
            content,
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
        if self.use_tls:
            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(message)
        else:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=30) as server:
                server.login(self.user, self.password)
                server.send_message(message)

    def _safe_error(self, error):
        return str(error).replace(self.password, "***")[:240]
