"""Asynchronous API client for PWiK Piaseczno iBOK."""
from __future__ import annotations

import asyncio
import base64
from datetime import date
import json
import logging
import math
from typing import Any

import aiohttp
from homeassistant.exceptions import HomeAssistantError

from .const import (
    BASE_URL,
    URL_ADD_READOUT,
    URL_ERRORS,
    URL_KILL_SESSION,
    URL_LOGIN,
    URL_NOTIFY_READOUT,
    URL_READOUTS_HISTORY,
    URL_REMOVE_READOUT,
)

_LOGGER = logging.getLogger(__name__)


class PwikAuthError(HomeAssistantError):
    """Authentication failed."""


class PwikApiError(HomeAssistantError):
    """PWiK API communication error."""


class PwikApiClient:
    """API client communicating with PWiK Piaseczno iBOK."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._username = username
        self._password = password
        self._lock = asyncio.Lock()
        self._is_logged_in = False
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/128.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "pl,en;q=0.9",
        }

    async def _kill_sessions(self) -> None:
        """Force terminate any existing or stuck sessions."""
        try:
            async with self._session.get(
                URL_KILL_SESSION,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                await resp.read()
                _LOGGER.debug("PWiK session killed successfully")
        except Exception as err:
            _LOGGER.debug("Error killing PWiK session: %s", err)

    async def login(self, force_kill: bool = False) -> bool:
        """Authenticate against PWiK iBOK with automatic session conflict recovery."""
        if force_kill:
            await self._kill_sessions()

        login_payload = {
            "JSTest": "ok",
            "user": self._username,
            "pass": self._password,
            "login": "Zaloguj",
        }

        try:
            async with self._session.post(
                URL_LOGIN,
                data=login_payload,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                text = await resp.text()

                if "loginWrongSessionLimit" in text:
                    _LOGGER.warning("PWiK session limit reached. Killing conflicting sessions and retrying...")
                    await self._kill_sessions()
                    async with self._session.post(
                        URL_LOGIN,
                        data=login_payload,
                        headers=self._headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as retry_resp:
                        text = await retry_resp.text()

                if "txtPassword" in text and "loginWrongSessionLimit" not in text and "Wyloguj" not in text:
                    raise PwikAuthError("Invalid username or password for PWiK iBOK")

                self._is_logged_in = True
                _LOGGER.debug("PWiK iBOK authenticated successfully")
                return True
        except PwikAuthError:
            raise
        except Exception as err:
            raise PwikApiError(f"Connection to PWiK iBOK failed: {err}") from err

    async def _check_server_errors(self) -> list[str]:
        """Fetch and decode flash messages/errors from ?module=Errors."""
        try:
            async with self._session.get(
                URL_ERRORS,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                raw_json = await resp.text()
                messages = json.loads(raw_json)
                errors = []
                for item in messages:
                    try:
                        err_txt = base64.b64decode(item.get("errorText_", "")).decode("utf-8")
                        err_type = base64.b64decode(item.get("errorType_", "")).decode("utf-8")
                        if err_type in ("ERR", "WRN"):
                            errors.append(err_txt)
                    except Exception:
                        continue
                return errors
        except Exception as err:
            _LOGGER.debug("Error checking PWiK errors endpoint: %s", err)
            return []

    async def _get_data_unlocked(self) -> dict[str, Any]:
        """Fetch meters status and readouts history without acquiring lock."""
        if not self._is_logged_in:
            await self.login(force_kill=True)

        try:
            async with self._session.get(
                URL_NOTIFY_READOUT,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                text = await resp.text()
                if "sessionExpired" in text or "txtPassword" in text:
                    _LOGGER.debug("Session expired. Re-authenticating...")
                    await self.login(force_kill=True)
                    async with self._session.get(
                        URL_NOTIFY_READOUT,
                        headers=self._headers,
                        timeout=aiohttp.ClientTimeout(total=20),
                    ) as retry_resp:
                        text = await retry_resp.text()

                meters = json.loads(text)
        except json.JSONDecodeError as err:
            raise PwikApiError("Malformed JSON response from PWiK NotifyReadout") from err
        except Exception as err:
            raise PwikApiError(f"Failed to fetch meters from PWiK: {err}") from err

        # Fetch history
        history = []
        try:
            async with self._session.get(
                URL_READOUTS_HISTORY,
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                hist_text = await resp.text()
                if "sessionExpired" not in hist_text:
                    history = json.loads(hist_text)
        except Exception as err:
            _LOGGER.debug("Failed to fetch PWiK history: %s", err)

        return {
            "meters": {m["numer_fabryczny"]: m for m in meters},
            "history": history,
        }

    async def get_data(self) -> dict[str, Any]:
        """Fetch meters status and readouts history (thread-safe)."""
        async with self._lock:
            return await self._get_data_unlocked()

    @staticmethod
    def format_reading(value: float | str, min_zakres: str) -> tuple[str, str]:
        """Format a reading into integer and fractional parts matching meter precision."""
        cleaned = str(value).strip().replace(",", ".")
        val_float = float(cleaned)

        decimals = 0
        if min_zakres and "." in min_zakres:
            decimals = len(min_zakres.split(".")[1])

        if decimals > 0:
            formatted = f"{val_float:.{decimals}f}"
            parts = formatted.split(".")
            return parts[0], parts[1]

        return str(int(math.floor(val_float))), ""

    async def submit_reading(
        self,
        meter_id: str,
        value: float | str,
        date_str: str,
        comment: str = "Home Assistant",
    ) -> bool:
        """Submit water meter reading with strict validation and error detection."""
        async with self._lock:
            # 1. Fetch fresh data safely inside lock
            data = await self._get_data_unlocked()
            meter = data["meters"].get(meter_id)
            if not meter:
                raise PwikApiError(f"Water meter {meter_id} not found in PWiK account")

            # Check if reading submission is already pending or in progress
            status = str(meter.get("ist", ""))
            if status == "1":
                raise PwikApiError(
                    f"Заявка на передачу показаний для счетчика {meter_id} уже ожидает подтверждения (статус: pending)"
                )
            if status == "2":
                raise PwikApiError(
                    f"Заявка на передачу показаний для счетчика {meter_id} уже находится в обработке (статус: in_progress)"
                )

            # Validate monotonous increase
            last_reading = float(meter.get("sl", 0))
            cleaned_val = float(str(value).strip().replace(",", "."))
            if cleaned_val < last_reading:
                raise PwikApiError(
                    f"New reading ({cleaned_val} m³) cannot be less than previous billing reading ({last_reading} m³)"
                )

            # Format integer and fractional parts matching meter precision
            nr_part, frac_part = self.format_reading(value, meter.get("min_zakres", "0.001"))

            # Normalize date to YYYY-MM-DD
            try:
                clean_date = date.fromisoformat(str(date_str).strip()[:10]).isoformat()
            except (ValueError, TypeError):
                clean_date = date.today().isoformat()

            # Date check: cannot be earlier than previous reading date
            last_date = meter.get("do")
            if last_date and clean_date < str(last_date).strip()[:10]:
                raise PwikApiError(
                    f"Дата показания ({clean_date}) не может быть раньше даты предыдущего биллингового показания ({last_date})"
                )

            # 2. Build multipart payload strictly matching PWiK portal fields
            form = aiohttp.FormData()
            form.add_field("id_wodom", str(meter.get("id_wodom", "")))
            form.add_field("odcz_poprz", str(meter.get("io", "0")))
            form.add_field("txtDateOfReading", clean_date)
            form.add_field("txtReadingNr", nr_part)
            form.add_field("txtReadingFrac", frac_part)
            form.add_field("txtDesc", comment)
            form.add_field(
                "txtAttachment",
                b"",
                filename="",
                content_type="application/octet-stream",
            )

            # 3. Post to action=add
            headers = self._headers.copy()
            headers["Referer"] = BASE_URL
            async with self._session.post(
                URL_ADD_READOUT,
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                await resp.read()

            # 4. Check for server errors
            errors = await self._check_server_errors()
            if errors:
                raise PwikApiError(f"PWiK rejected reading submission: {', '.join(errors)}")

            _LOGGER.info(
                "Successfully submitted reading %s.%s (date: %s) for water meter %s",
                nr_part,
                frac_part,
                clean_date,
                meter_id,
            )
            return True

    async def cancel_reading(self, meter_id: str) -> bool:
        """Cancel a pending reading submission."""
        async with self._lock:
            data = await self._get_data_unlocked()
            meter = data["meters"].get(meter_id)
            if not meter:
                raise PwikApiError(f"Water meter {meter_id} not found")

            reading_id = meter.get("id")
            if not reading_id or str(meter.get("ist")) != "1":
                raise PwikApiError(f"No cancellable pending reading found for meter {meter_id}")

            async with self._session.post(
                URL_REMOVE_READOUT,
                data={"txtIdOdczytu": str(reading_id)},
                headers=self._headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                await resp.read()

            errors = await self._check_server_errors()
            if errors:
                raise PwikApiError(f"PWiK rejected cancellation: {', '.join(errors)}")

            _LOGGER.info("Successfully cancelled pending reading for meter %s", meter_id)
            return True
