"""Pure validation. Email and model output are always untrusted data."""
import calendar
import hashlib
import json
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit, urlencode, quote
from pydantic import BaseModel, ConfigDict, Field, field_validator

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SELECT = "id,internetMessageId,subject,body,from,toRecipients,ccRecipients,receivedDateTime,sentDateTime,lastModifiedDateTime,webLink,parentFolderId"


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def utc(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return result.astimezone(timezone.utc)


def month_end(start, end):
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return min(start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1])), end)


def graph_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "graph.microsoft.com" or parsed.username
            or parsed.password or parsed.fragment or not parsed.path.startswith("/v1.0/me/") or "\\" in value):
        raise ValueError("Only Microsoft Graph /v1.0/me read URLs are accepted")
    return value


def initial_url(stream, folder, start=None, end=None):
    if stream == "live":
        return f"{GRAPH_ROOT}/me/mailFolders/{quote(folder, safe='')}/messages/delta?" + urlencode({"$select": SELECT, "$top": 100})
    return f"{GRAPH_ROOT}/me/messages?" + urlencode({
        "$select": SELECT, "$top": 100, "$orderby": "receivedDateTime asc",
        "$filter": f"receivedDateTime ge {start.isoformat()} and receivedDateTime lt {end.isoformat()}",
    })


def normalize_message(raw):
    if not isinstance(raw.get("id"), str) or not raw["id"]:
        raise ValueError("Immutable Graph message ID is required")
    if not isinstance(raw.get('receivedDateTime'), str):
        raise ValueError('Received timestamp is required')
    body = raw.get("body") or {}
    if body.get("contentType", "text").lower() != "text":
        raise ValueError("Graph must return text bodies")
    sender = ((raw.get("from") or {}).get("emailAddress") or {}).get("address", "").strip().lower()
    subject, text = raw.get("subject") or "", body.get("content") or ""
    if len(text) > 1_000_000 or len(subject) > 10_000:
        raise ValueError("Message exceeds processing size limit")
    source = f"Subject: {subject}\nFrom: {sender}\n\n{text}"
    internet_id = (raw.get("internetMessageId") or "").strip()
    return {
        "provider_id": raw["id"], "canonical_key": digest("internet:" + sender + ':' + internet_id if internet_id else "graph:" + raw["id"]),
        "subject": subject, "sender": sender, "source": source, "content_hash": digest(source),
        "received_at": utc(raw["receivedDateTime"]),
        "modified_at": utc(raw.get("lastModifiedDateTime") or raw["receivedDateTime"]),
        "web_link": raw.get("webLink", ""),
    }


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    quote: str = Field(min_length=1, max_length=4000)


class Transaction(Evidence):
    kind: Literal["invoice", "payment", "credit", "refund"]
    direction: Literal["payable", "receivable", "unknown"]
    vendor: str = Field(min_length=1, max_length=300)
    reference: str | None = Field(default=None, max_length=200)
    amount: Decimal = Field(gt=0, max_digits=20, decimal_places=4)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    due_date: date | None = None
    confidence: float = Field(ge=0, le=1)


class PaymentMethod(Evidence):
    method: Literal["bank_transfer", "ach", "wire", "card", "check", "paypal", "other"]
    vendor: str = Field(min_length=1, max_length=300)


class Contact(Evidence):
    email: str = Field(max_length=320)
    name: str = Field(default="", max_length=200)
    role: Literal["accounts_payable", "accounts_receivable", "billing", "finance", "other"]

    @field_validator("email")
    @classmethod
    def email_shape(cls, value):
        value = value.lower().strip()
        if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+", value):
            raise ValueError("Invalid email")
        return value


class Extraction(StrictModel):
    transactions: list[Transaction] = Field(default_factory=list, max_length=100)
    payment_methods: list[PaymentMethod] = Field(default_factory=list, max_length=100)
    contacts: list[Contact] = Field(default_factory=list, max_length=100)


def grounded(result, source):
    for item in [*result.transactions, *result.payment_methods, *result.contacts]:
        if item.quote not in source:
            raise ValueError("Evidence quote is absent from source")
    for item in result.transactions:
        numbers = re.findall(r"(?<![\w])\d[\d,]*(?:\.\d+)?", item.quote)
        if item.amount not in [Decimal(n.replace(",", "")) for n in numbers]:
            raise ValueError("Amount is absent from evidence")
        if item.reference and item.reference.casefold() not in item.quote.casefold():
            raise ValueError("Reference is absent from evidence")
        if not re.search(r'\b'+re.escape(item.currency)+r'\b',item.quote):
            raise ValueError("Explicit ISO currency is required in evidence")
        if item.vendor.casefold() not in item.quote.casefold():
            raise ValueError("Vendor is absent from evidence")
        if item.due_date and not any(s in item.quote for s in [
                item.due_date.isoformat(), item.due_date.strftime('%B %d, %Y'),
                item.due_date.strftime('%B ') + str(item.due_date.day) + item.due_date.strftime(', %Y')]):
            raise ValueError("Unambiguous due date is absent from evidence")
    for item in result.contacts:
        if item.email not in item.quote.lower():
            raise ValueError("Contact email is absent from evidence")
        terms={'accounts_payable':['accounts payable','payables'], 'accounts_receivable':['accounts receivable','receivables'],
               'billing':['billing'], 'finance':['finance','financial'], 'other':['finance','billing','accounts payable','accounts receivable']}
        if not any(term in item.quote.lower() for term in terms[item.role]):
            raise ValueError('Finance role is absent from evidence')
        if item.name and item.name.casefold() not in item.quote.casefold():
            raise ValueError('Contact name is absent from evidence')
    for item in result.payment_methods:
        terms={'bank_transfer':['bank transfer'], 'ach':['ach'], 'wire':['wire'], 'card':['card','visa','mastercard','amex'],
               'check':['check','cheque'], 'paypal':['paypal'], 'other':['payment method']}
        if item.vendor.casefold() not in item.quote.casefold() or not any(re.search(r'\b'+re.escape(term)+r'\b',item.quote,re.I) for term in terms[item.method]):
            raise ValueError('Vendor or payment method is absent from evidence')
    return result


def transaction_key(mailbox, message_key, vendor_domain, item):
    scope = [vendor_domain, item.vendor.casefold(), item.reference.strip().casefold()] if item.kind == 'invoice' and item.reference and vendor_domain else [message_key, item.vendor.casefold(), item.reference]
    return digest(json.dumps([mailbox, scope, item.kind, item.direction, str(item.amount.normalize()), item.currency], sort_keys=True))
