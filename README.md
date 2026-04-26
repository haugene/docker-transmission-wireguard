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

I've also changed the Transmission settings handling a bit. The container will still accept
environment variables, but defaults are read from a file. This is to de-clutter the Dockerfile a bit.
There are still a handful of default settings being set as ENV variables in the Dockerfile to
get the PUID/PGID working like it used to. I'll try to clean up that as well.

If you're already running the old image, I'd recommend setting the ports option to: `- 9092:9091`.
That way you'll map it to port 9092 locally and you can have them both running at the same time.


### Example Docker Compose file:
```yaml
services:
  transmission-wireguard:
    networks: 
      - wg-trans_default
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
networks:
  wg-trans_default:
    name: wg-trans_default
    enable_ipv6: false
```
