# Wireguard and Transmission with WebUI

This project creates a Docker image that bundles Wireguard and Transmission.
It sets up networking in a way that ensures Transmission traffic is always routed through the VPN.

## Work in progress

This image is under construction. Breaking changes might occur without warning!

If you're already running an instance of `haugene/transmission-openvpn`, _I would not recommend_
swapping your installation for this image just yet. Please test it and report any issues.

## Quick start

The new image differs a bit from the old, and I'll hopefully get to document that better soon.
But from the "getting it to run" perspective, the first things that come to mind are:

* You need to mount a config file
* It requires running in privileged mode

This might change, but this is how it's running now.

Transmission settings are overridden via `TRANSMISSION_*` environment variables
(for example `TRANSMISSION_PEER_PORT`). On first run those are written into a new
`settings.json`; on later starts they overlay the existing file. A few path/umask
defaults are set as `ENV` in the Dockerfile for PUID/PGID layouts.

If you're already running the old image, I'd recommend setting the ports option to: `- 9092:9091`.
That way you'll map it to port 9092 locally and you can have them both running at the same time.


### Example Docker Compose file:
```yaml
services:
  transmission-wireguard:
    # No versioned tags yet, pulling latest build from the main branch.
    image: haugene/transmission-wireguard:main
    container_name: wg-main
    privileged: true
    ports:
      - 9091:9091
    volumes:
      - /your/storage/path/:/data # where transmission will store downloads
      - /your/config/path/:/config # where transmission-home (state) is stored
      - /your/wireguard-configs/:/wg-config/ # example mount for wireguard configs
    environment:
      - PUID=1000
      - PGID=1000
      - CONFIG_FILE=/wg-config/my_wg.conf  # A config file within your wireguard config mount
    logging:
      driver: json-file
      options:
        max-size: 10m
```

## DNS and WireGuard endpoints

The container moves the Docker network interface into a separate network namespace so
Transmission only has the WireGuard interface. That means hostname lookups for a
WireGuard `Endpoint` cannot wait until after setup — there is no path to a resolver
in that namespace until the tunnel is up.

If your config uses a DNS name in `Endpoint` (instead of an IP), the container
resolves it **once at startup** via `dig` to `WG_BOOTSTRAP_DNS` (default `1.1.1.1`),
then rewrites the config to use that IP before moving the interface. That single
bootstrap lookup goes outside the tunnel; later DNS (with the default override to
Cloudflare) goes through WireGuard.

| Variable | Purpose |
| --- | --- |
| `WG_BOOTSTRAP_DNS` | IP of the resolver used only for Endpoint hostname lookup (default `1.1.1.1`). Must be an IP, not a hostname. |
| `ACCEPT_DNS_PRIVACY_LOSS=true` | Do not replace `/etc/resolv.conf`. Docker's embedded resolver (`127.0.0.11`) may then answer DNS outside the tunnel. Prefer leaving this unset. |
