import sys
import logging
from unittest.mock import MagicMock

# pylint: disable=too-few-public-methods

# Mock plugins.base_plugin
plugins = MagicMock()
base_plugin = MagicMock()


class BaseGPSPlugin:
    def __init__(self, config):
        self._config = config

    def get_decrypted_config(self):
        return self._config


class CallsignMappable:
    pass


class FieldMetadata:
    def __init__(self, *args, **kwargs):
        pass


class PluginConfigField:
    def __init__(self, *args, **kwargs):
        pass


base_plugin.BaseGPSPlugin = BaseGPSPlugin
base_plugin.CallsignMappable = CallsignMappable
base_plugin.FieldMetadata = FieldMetadata
base_plugin.PluginConfigField = PluginConfigField

sys.modules["plugins"] = plugins
sys.modules["plugins.base_plugin"] = base_plugin

# Mock services.logging_service
services = MagicMock()
logging_service = MagicMock()


def get_module_logger(name):
    return logging.getLogger(name)


logging_service.get_module_logger = get_module_logger
sys.modules["services"] = services
sys.modules["services.logging_service"] = logging_service
