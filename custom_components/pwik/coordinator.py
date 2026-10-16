"""DataUpdateCoordinator for PWiK Piaseczno iBOK."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import PwikApiClient, PwikApiError, PwikAuthError
from .const import DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class PwikDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching PWiK iBOK data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: PwikApiClient,
        update_interval: int = DEFAULT_UPDATE_INTERVAL,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=update_interval),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from PWiK iBOK."""
        try:
            return await self.api.get_data()
        except PwikAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except PwikApiError as err:
            raise UpdateFailed(f"Error communicating with PWiK API: {err}") from err
