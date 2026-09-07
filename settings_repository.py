import hashlib
import json
import os
import tempfile
import threading
from dataclasses import dataclass


class SettingsConflictError(RuntimeError):
    pass


@dataclass(frozen=True)
class SettingsSnapshot:
    settings: dict
    etag: str | None


class FileSettingsRepository:
    def __init__(self, path, defaults):
        self._path = path
        self._defaults = defaults.copy()
        self._lock = threading.Lock()

    @staticmethod
    def _etag(content):
        return hashlib.sha256(content).hexdigest()

    def load(self):
        if not os.path.exists(self._path):
            return SettingsSnapshot(self._defaults.copy(), None)

        with open(self._path, "rb") as settings_file:
            content = settings_file.read()
        settings = self._defaults | json.loads(content)
        return SettingsSnapshot(settings, self._etag(content))

    def save(self, settings, expected_etag):
        content = json.dumps(settings, indent=2).encode("utf-8")
        directory = os.path.dirname(self._path)

        with self._lock:
            current = self.load()
            if current.etag != expected_etag:
                raise SettingsConflictError("Settings were changed by another administrator.")

            file_descriptor, temporary_path = tempfile.mkstemp(dir=directory, prefix="settings-", suffix=".tmp")
            try:
                with os.fdopen(file_descriptor, "wb") as settings_file:
                    settings_file.write(content)
                os.replace(temporary_path, self._path)
            except Exception:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)
                raise

        return SettingsSnapshot(settings.copy(), self._etag(content))


class AzureAppConfigurationSettingsRepository:
    def __init__(self, endpoint, key, label, defaults, managed_identity_client_id=None, client=None):
        if client is None:
            from azure.appconfiguration import AzureAppConfigurationClient
            from azure.identity import ManagedIdentityCredential

            credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
            client = AzureAppConfigurationClient(base_url=endpoint, credential=credential)

        self._client = client
        self._key = key
        self._label = label
        self._defaults = defaults.copy()

    def load(self):
        from azure.core.exceptions import ResourceNotFoundError

        try:
            setting = self._client.get_configuration_setting(key=self._key, label=self._label)
        except ResourceNotFoundError:
            return SettingsSnapshot(self._defaults.copy(), None)

        settings = self._defaults | json.loads(setting.value)
        return SettingsSnapshot(settings, setting.etag)

    def save(self, settings, expected_etag):
        from azure.appconfiguration import ConfigurationSetting
        from azure.core import MatchConditions
        from azure.core.exceptions import ResourceExistsError, ResourceModifiedError

        setting = ConfigurationSetting(
            key=self._key,
            label=self._label,
            value=json.dumps(settings),
            content_type="application/json",
        )
        try:
            if expected_etag is None:
                saved = self._client.add_configuration_setting(setting)
            else:
                saved = self._client.set_configuration_setting(
                    setting,
                    etag=expected_etag,
                    match_condition=MatchConditions.IfNotModified,
                )
        except (ResourceExistsError, ResourceModifiedError) as error:
            raise SettingsConflictError("Settings were changed by another administrator.") from error

        return SettingsSnapshot(settings.copy(), saved.etag)


def create_settings_repository(settings_file, defaults):
    endpoint = os.environ.get("AZURE_APPCONFIG_ENDPOINT")
    if not endpoint:
        return FileSettingsRepository(settings_file, defaults)

    return AzureAppConfigurationSettingsRepository(
        endpoint=endpoint,
        key=os.environ.get("AZURE_APPCONFIG_SETTINGS_KEY", "fabric-governance-hub:settings"),
        label=os.environ.get("AZURE_APPCONFIG_LABEL"),
        defaults=defaults,
        managed_identity_client_id=os.environ.get("AZURE_CLIENT_ID"),
    )