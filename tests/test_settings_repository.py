import json
import os
import tempfile
import unittest

from azure.appconfiguration import ConfigurationSetting
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError

from settings_repository import (
    AzureAppConfigurationSettingsRepository,
    FileSettingsRepository,
    SettingsConflictError,
)


class InMemoryAppConfigurationClient:
    def __init__(self):
        self.setting = None
        self.revision = 0

    def get_configuration_setting(self, key, label):
        if self.setting is None:
            raise ResourceNotFoundError()
        return self.setting

    def add_configuration_setting(self, setting):
        if self.setting is not None:
            raise ResourceExistsError()
        return self._store(setting)

    def set_configuration_setting(self, setting, match_condition, etag):
        if self.setting is None or self.setting.etag != etag:
            raise ResourceModifiedError()
        return self._store(setting)

    def _store(self, setting):
        self.revision += 1
        self.setting = ConfigurationSetting(
            key=setting.key,
            label=setting.label,
            value=setting.value,
            content_type=setting.content_type,
            etag=f'"{self.revision}"',
        )
        return self.setting


class FileSettingsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "settings.json")
        self.defaults = {"environments": ["Dev"], "branches": ["main"]}
        self.repository = FileSettingsRepository(self.path, self.defaults)

    def tearDown(self):
        self.directory.cleanup()

    def test_returns_defaults_when_file_does_not_exist(self):
        snapshot = self.repository.load()

        self.assertEqual(self.defaults, snapshot.settings)
        self.assertIsNone(snapshot.etag)

    def test_saves_and_loads_settings_with_etag(self):
        settings = {"environments": ["Dev", "Prd"], "branches": ["main"]}

        saved = self.repository.save(settings, expected_etag=None)
        loaded = self.repository.load()

        self.assertEqual(settings, loaded.settings)
        self.assertEqual(saved.etag, loaded.etag)
        with open(self.path, encoding="utf-8") as settings_file:
            self.assertEqual(settings, json.load(settings_file))

    def test_rejects_stale_write(self):
        first = self.repository.save(self.defaults, expected_etag=None)
        self.repository.save({**self.defaults, "branches": ["develop"]}, first.etag)

        with self.assertRaises(SettingsConflictError):
            self.repository.save({**self.defaults, "branches": ["release"]}, first.etag)


class AzureAppConfigurationSettingsRepositoryTests(unittest.TestCase):
    def test_rejects_stale_write(self):
        defaults = {"environments": ["Dev"], "branches": ["main"]}
        client = InMemoryAppConfigurationClient()
        repository = AzureAppConfigurationSettingsRepository(
            endpoint="https://example.azconfig.io",
            key="test:settings",
            label="test",
            defaults=defaults,
            client=client,
        )
        created = repository.save(defaults, expected_etag=None)
        stale = repository.load()
        repository.save({**defaults, "branches": ["develop"]}, created.etag)

        with self.assertRaises(SettingsConflictError):
            repository.save({**defaults, "branches": ["release"]}, stale.etag)


if __name__ == "__main__":
    unittest.main()