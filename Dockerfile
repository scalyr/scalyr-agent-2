FROM mcr.microsoft.com/windows/servercore:ltsc2019

SHELL ["powershell", "-Command", "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';"]

RUN Set-ExecutionPolicy Bypass -Scope Process -Force; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))
RUN choco install python git -y

RUN python -m pip install --upgrade pip
RUN pip install --upgrade --no-cache-dir \
    orjson==3.6.8 \
    zstandard==0.17.0  \
    lz4==4.0.0 \
    requests==2.25.1 \
    docker==4.1.0 \
    psutil

WORKDIR /Scalyr
ADD . /Scalyr
ADD ./docker/k8s-config/ /Scalyr/config

RUN Get-Content /Scalyr/certs/*.pem | Set-Content /Scalyr/certs/ca_certs.crt
RUN "[Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'Machine')"
ENV SCALYR_STDOUT_SEVERITY ERROR
ENV SCALYR_K8S_KUBELET_CA_CERT /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
ENV SCALYR_K8S_SERVICE_ACCOUNT_CERT /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
CMD ["python", "-X", "utf8", "/Scalyr/scalyr_agent/agent_main.py", "--no-fork", "--no-change-user", "--verbose", "start"]