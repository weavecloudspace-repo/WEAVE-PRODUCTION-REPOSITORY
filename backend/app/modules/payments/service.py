from __future__ import annotations

from typing import Any, Mapping

from app.modules.payments.providers.paystack import PaystackClient
from app.modules.payments.schemas import PaymentCheckoutSession, VerifiedPayment


class PaymentEngineError(RuntimeError):
    """Base error raised by shared payment infrastructure."""


class PaymentVerificationError(PaymentEngineError):
    """Raised when provider data does not match a backend-owned payment expectation."""


class PaymentNotCompletedError(PaymentVerificationError):
    """A known non-successful transaction outcome, not an integrity mismatch."""

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__("Payment has not completed.")


class PaymentEngine:
    """Provider-facing payment engine with no product or pricing knowledge."""

    @classmethod
    async def initialize_checkout(
        cls,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        callback_url: str,
        metadata: dict[str, Any],
    ) -> PaymentCheckoutSession:
        if type(amount_kobo) is not int or amount_kobo <= 0:
            raise ValueError("amount_kobo must be a positive integer.")
        normalized_reference = str(reference or "").strip()
        if not normalized_reference:
            raise ValueError("reference cannot be blank.")
        response = await PaystackClient().initialize_transaction(
            email=email,
            amount_kobo=amount_kobo,
            reference=normalized_reference,
            callback_url=callback_url,
            metadata=metadata,
        )
        data = response.get("data") or {}
        authorization_url = str(data.get("authorization_url") or "").strip()
        access_code = str(data.get("access_code") or "").strip()
        if not authorization_url or not access_code:
            raise PaymentEngineError("Paystack did not return a usable checkout session.")
        return PaymentCheckoutSession(
            reference=normalized_reference,
            authorization_url=authorization_url,
            access_code=access_code,
        )

    @classmethod
    async def verify_transaction(
        cls,
        *,
        reference: str,
        expected_amount_kobo: int,
        expected_currency: str,
        expected_metadata: Mapping[str, object] | None = None,
    ) -> VerifiedPayment:
        payload = await PaystackClient().verify_transaction(reference=reference)
        raw_data = payload.get("data")
        data = raw_data if isinstance(raw_data, Mapping) else payload
        provider_status = data.get("status")
        if (
            data.get("reference") == reference
            and isinstance(provider_status, str)
            and provider_status in {
                "abandoned", "failed", "pending", "ongoing", "processing", "queued"
            }
        ):
            raise PaymentNotCompletedError(provider_status)
        return cls.validate_successful_payload(
            payload,
            expected_reference=reference,
            expected_amount_kobo=expected_amount_kobo,
            expected_currency=expected_currency,
            expected_metadata=expected_metadata,
        )

    @staticmethod
    def validate_successful_payload(
        payload: Mapping[str, Any],
        *,
        expected_reference: str,
        expected_amount_kobo: int,
        expected_currency: str,
        expected_metadata: Mapping[str, object] | None = None,
    ) -> VerifiedPayment:
        raw_data = payload.get("data")
        data = raw_data if isinstance(raw_data, Mapping) else payload
        reference = str(data.get("reference") or "")
        if (
            data.get("status") != "success"
            or reference != expected_reference
            or int(data.get("amount") or -1) != expected_amount_kobo
            or str(data.get("currency") or "") != expected_currency
        ):
            raise PaymentVerificationError(
                "Verified payment did not match the backend payment expectation."
            )
        metadata_value = data.get("metadata")
        metadata = dict(metadata_value) if isinstance(metadata_value, Mapping) else {}
        if expected_metadata:
            for key, expected_value in expected_metadata.items():
                actual_value = metadata.get(key)
                if str(actual_value) != str(expected_value):
                    raise PaymentVerificationError(
                        f"Verified payment metadata did not match expected field {key!r}."
                    )
        provider_transaction_id = data.get("id")
        return VerifiedPayment(
            reference=reference,
            amount_kobo=expected_amount_kobo,
            currency=expected_currency,
            provider_transaction_id=(
                str(provider_transaction_id) if provider_transaction_id is not None else None
            ),
            metadata=metadata,
            raw_payload=dict(data),
        )
