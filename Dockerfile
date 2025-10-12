# Helper image to install Transmission UIs
FROM alpine:latest AS transmissionui

RUN apk --no-cache add curl jq \
    && mkdir -p /opt/transmission-ui \
    && echo "Install Shift" \
    && wget -qO- https://github.com/killemov/Shift/archive/master.tar.gz | tar xz -C /opt/transmission-ui \
    && mv /opt/transmission-ui/Shift-master /opt/transmission-ui/shift \
    && echo "Install Flood for Transmission" \
    && wget -qO- https://github.com/johman10/flood-for-transmission/releases/download/latest/flood-for-transmission.tar.gz | tar xz -C /opt/transmission-ui \
    && echo "Install Combustion" \
    && wget -qO- https://github.com/Secretmapper/combustion/archive/release.tar.gz | tar xz -C /opt/transmission-ui \
    && echo "Install kettu" \
    && wget -qO- https://github.com/endor/kettu/archive/master.tar.gz | tar xz -C /opt/transmission-ui \
    && mv /opt/transmission-ui/kettu-master /opt/transmission-ui/kettu \
    && echo "Install Transmissionic" \
    && wget -qO- https://github.com/6c65726f79/Transmissionic/releases/download/v1.8.0/Transmissionic-webui-v1.8.0.zip | unzip -q - \
    && mv web /opt/transmission-ui/transmissionic

# Main image
FROM ubuntu:24.04

VOLUME /data
VOLUME /config

COPY --from=transmissionui /opt/transmission-ui /opt/transmission-ui

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    dumb-init transmission-daemon \
    tzdata dnsutils iputils-ping ufw iproute2 \
    openssh-client git jq curl wget unrar unzip bc \
    # New for this image
    wireguard nginx \
    # End new for this image
    && rm -rf /tmp/* /var/tmp/* /var/lib/apt/lists/* \
    && useradd -u 911 -U -d /config -s /bin/false abc \
    && usermod -G users abc


ADD start.sh /opt/wireguard/start.sh
ADD nginx_server.conf /opt/nginx/server.conf
ADD transmission-default-settings.json /opt/transmission/default-settings.json
ADD updateSettings.py /opt/transmission/
ADD userSetup.sh /opt/transmission/

# Set some environment variables needed in various scripts
ENV TRANSMISSION_HOME=/config/transmission-home \
    TRANSMISSION_DOWNLOAD_DIR=/data/completed \
    TRANSMISSION_INCOMPLETE_DIR=/data/incomplete \
    TRANSMISSION_WATCH_DIR=/data/watch \
    GLOBAL_APPLY_PERMISSIONS=true \
    TRANSMISSION_UMASK=2

# Get base_revision passed as a build argument and set it as env var
ARG REVISION
ENV REVISION=${REVISION:-""}

CMD ["dumb-init", "-vv", "/opt/wireguard/start.sh"]