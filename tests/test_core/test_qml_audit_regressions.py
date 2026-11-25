"""Regressions discovered during the QML audit."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config.settings import Settings
from core.application_service import ApplicationService


@pytest.mark.parametrize('installed,preload,expected',[(True,True,True),(False,True,False),(True,False,False)])
def test_preload_uses_inventory_model_field(installed,preload,expected):
    service=ApplicationService.__new__(ApplicationService)
    start=Mock()
    service.controller=SimpleNamespace(settings=Settings(model_size='medium',preload_model=preload),list_models=lambda:[{'model':'medium','installed':installed}],ensure_backend_started=start)
    service.submit=Mock()
    service.preload_model_if_requested()
    assert service.submit.called == expected
    if expected:
        service.submit.assert_called_once_with('preload-model',start,'backend_preload_error')


def test_installed_legacy_models_stay_listed_so_they_can_be_deleted():
    service = ApplicationService.__new__(ApplicationService)
    service.controller = SimpleNamespace(
        list_models=lambda: [
            {"model": "large-v3", "installed": False},
            {"model": "large-v3-turbo", "installed": True},
            {"model": "medium", "installed": False},
        ]
    )
    assert [row["model"] for row in service.list_models()] == [
        "large-v3",
        "large-v3-turbo",
    ]
