"""A real HA runtime with a temporary configuration, no real AVS requests."""

import shutil
from pathlib import Path

import pytest
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_setup as setup_loader


@pytest.fixture
async def hass(tmp_path):
    source = Path(__file__).parents[1] / "custom_components"
    shutil.copytree(
        source, tmp_path / "custom_components", ignore=shutil.ignore_patterns("__pycache__")
    )
    instance = HomeAssistant(str(tmp_path))
    instance.config.language = "it"
    instance.config_entries = ConfigEntries(instance, {})
    setup_loader(instance)
    await instance.config_entries.async_initialize()
    assert await async_load_base_functionality(instance)
    yield instance
    await instance.async_stop(force=True)
