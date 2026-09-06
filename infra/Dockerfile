FROM python:3.12-slim-trixie

ARG POWERSHELL_VERSION=7.4.19
ARG AZ_ACCOUNTS_VERSION=5.5.3
ARG AZ_RESOURCES_VERSION=10.2.0
ARG DATA_GATEWAY_PROFILE_VERSION=3000.318.6
ARG DATA_GATEWAY_VERSION=3000.318.6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    POWERSHELL_TELEMETRY_OPTOUT=1 \
    AZ_ACCOUNTS_VERSION=${AZ_ACCOUNTS_VERSION} \
    AZ_RESOURCES_VERSION=${AZ_RESOURCES_VERSION} \
    DATA_GATEWAY_PROFILE_VERSION=${DATA_GATEWAY_PROFILE_VERSION} \
    DATA_GATEWAY_VERSION=${DATA_GATEWAY_VERSION}

RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates curl libicu76 libssl3 \
    && mkdir -p /opt/microsoft/powershell/7 \
    && curl --fail --location --show-error \
      "https://github.com/PowerShell/PowerShell/releases/download/v${POWERSHELL_VERSION}/powershell-${POWERSHELL_VERSION}-linux-x64.tar.gz" \
      --output /tmp/powershell.tar.gz \
    && tar --extract --gzip --file /tmp/powershell.tar.gz --directory /opt/microsoft/powershell/7 \
    && chmod +x /opt/microsoft/powershell/7/pwsh \
    && ln -s /opt/microsoft/powershell/7/pwsh /usr/local/bin/pwsh \
    && rm /tmp/powershell.tar.gz \
    && rm -rf /var/lib/apt/lists/*

RUN pwsh -NoLogo -NoProfile -Command \
    'Set-PSRepository -Name PSGallery -InstallationPolicy Trusted; \
    Install-Module Az.Accounts -RequiredVersion $env:AZ_ACCOUNTS_VERSION -Scope AllUsers -Force; \
    Install-Module Az.Resources -RequiredVersion $env:AZ_RESOURCES_VERSION -Scope AllUsers -Force; \
    Install-Module DataGateway.Profile -RequiredVersion $env:DATA_GATEWAY_PROFILE_VERSION -Scope AllUsers -Force; \
    Install-Module DataGateway -RequiredVersion $env:DATA_GATEWAY_VERSION -Scope AllUsers -Force; \
    Import-Module Az.Accounts -RequiredVersion $env:AZ_ACCOUNTS_VERSION -ErrorAction Stop; \
    Import-Module Az.Resources -RequiredVersion $env:AZ_RESOURCES_VERSION -ErrorAction Stop; \
    Import-Module DataGateway.Profile -RequiredVersion $env:DATA_GATEWAY_PROFILE_VERSION -ErrorAction Stop; \
    Import-Module DataGateway -RequiredVersion $env:DATA_GATEWAY_VERSION -ErrorAction Stop'

WORKDIR /app

COPY infra/requirements.azure.txt ./requirements.azure.txt
RUN pip install --no-cache-dir --requirement requirements.azure.txt

COPY app.py gateway_session.py ./
COPY scripts ./scripts
COPY templates ./templates

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && chown -R app:app /app

USER app

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--timeout", "120", "app:app"]