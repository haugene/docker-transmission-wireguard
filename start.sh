#! /bin/bash

# Exit on error
set -e

if [[ -n "$REVISION" ]]; then
  echo "Image revision: $REVISION"
fi

echo "Current public IP is:"
curl --silent -w "\n" ipecho.net/plain

if ip netns ls | grep -q "physical"
then
    # Dangling network from previous run, clean up
    echo "Clean up dangling network namespaces"
    ip -all netns delete
fi

# Grab information from the default interface set up in the container
GW=$(/sbin/ip route list match 0.0.0.0 | awk '{print $3}')
INT=$(/sbin/ip route list match 0.0.0.0 | awk '{print $5}')
INT_IP=$(ip -f inet addr show "$INT" | awk '/inet / {print $2}')
INT_BRD=$(ip -f inet addr show "$INT" | awk '/inet / {print $4}')

echo "Found default container interface, will use this in setup:"
echo "Interface: $INT"
echo "Gateway: $GW"
echo "Interface address: $INT_IP"
echo "Interface broadcast: $INT_BRD"

# Override DNS to Cloudflare (IPv4 + IPv6) unless SKIP_DNS_OVERRIDE is set to true (case insensitive)
if [ -z "${SKIP_DNS_OVERRIDE}" ] || ! [[ "${SKIP_DNS_OVERRIDE,,}" == "true" ]]; then
  echo "Overriding DNS to Cloudflare (IPv4 + IPv6)"
  cat > /etc/resolv.conf << EOF
nameserver 1.1.1.1
nameserver 1.0.0.1
nameserver 2606:4700:4700::1111
nameserver 2606:4700:4700::1001
EOF
else
  echo "Skipping DNS override due to SKIP_DNS_OVERRIDE=${SKIP_DNS_OVERRIDE}"
fi

echo "DNS config:"
cat /etc/resolv.conf

# Create a "physical" network namespace and move our eth0 there
ip netns ls
ip netns add physical
ip link set eth0 netns physical

# Create wireguard interface in physical namespace and move it to the default namespace
ip -n physical link add wg0 type wireguard
ip -n physical link set wg0 netns 1

# Restore IP and route configuration for the default interface, start it
ip -n physical addr add "$INT_IP" dev "$INT" brd "$INT_BRD"
ip -n physical link set "$INT" up
#ip -n physical link set lo up
ip -n physical route add default via "$GW" dev "$INT"

#
# Setting up Wireguard
# We need to make the wg0 interface separately to do the namespace linking
# and we can't use wg-quick after that. So the rest is done "manually".
#

# Extract IPv4 and IPv6 addresses from WireGuard config
# Config format: Address = 10.x.x.x/32, fd00::x/128
ipv4_address=$(grep "Address" "$CONFIG_FILE" | awk '{print $NF}' | tr ',' '\n' | grep -E '^[0-9]+\.' | head -1)
ipv6_address=$(grep "Address" "$CONFIG_FILE" | awk '{print $NF}' | tr ',' '\n' | grep -E '^[a-fA-F0-9:]+/' | head -1)

echo "WireGuard IPv4 address: $ipv4_address"
echo "WireGuard IPv6 address: ${ipv6_address:-none}"

ip addr add "$ipv4_address" dev wg0

# Add IPv6 if present in config
if [ -n "$ipv6_address" ]; then
  echo "Adding IPv6 address: $ipv6_address"
  ip -6 addr add "$ipv6_address" dev wg0
fi

stripped_config_file=$(mktemp)
wg-quick strip "$CONFIG_FILE" > "$stripped_config_file"

echo "Will use wg config from $stripped_config_file"
wg setconf wg0 "$stripped_config_file"
ip link set wg0 up
#ip link set lo up
ip route add default dev wg0

# Add IPv6 default route if IPv6 is configured
if [ -n "$ipv6_address" ]; then
  echo "Adding IPv6 default route via wg0"
  ip -6 route add default dev wg0
fi

#
# Wireguard interface is now set up and should be connected
#
echo "Wireguard is up - new IP:"
curl --silent -w "\n" ipecho.net/plain

#
# Set up iptables kill switch to prevent IP leaks
#
setup_killswitch() {
  echo "Setting up iptables kill switch..."

  # Get WireGuard server endpoint for allowed exception
  wg_endpoint=$(wg show wg0 endpoints | awk '{print $2}' | cut -d: -f1)
  wg_port=$(wg show wg0 endpoints | awk '{print $2}' | cut -d: -f2)

  if [ -z "$wg_endpoint" ] || [ -z "$wg_port" ]; then
    echo "ERROR: Failed to get WireGuard endpoint. Cannot configure kill switch safely."
    exit 1
  fi

  echo "WireGuard endpoint: $wg_endpoint:$wg_port"

  #
  # IPv4 Rules
  #

  # Flush existing rules
  iptables -F OUTPUT
  iptables -F INPUT

  # Default policy: DROP all outbound traffic
  iptables -P OUTPUT DROP
  iptables -P INPUT DROP
  iptables -P FORWARD DROP

  # Allow loopback
  iptables -A OUTPUT -o lo -j ACCEPT
  iptables -A INPUT -i lo -j ACCEPT

  # Allow all traffic through WireGuard interface
  iptables -A OUTPUT -o wg0 -j ACCEPT
  iptables -A INPUT -i wg0 -j ACCEPT

  # Allow ICMP for diagnostics and Path MTU Discovery (through wg0 only)
  iptables -A OUTPUT -o wg0 -p icmp --icmp-type echo-request -j ACCEPT
  iptables -A INPUT -i wg0 -p icmp --icmp-type echo-reply -j ACCEPT
  iptables -A INPUT -i wg0 -p icmp --icmp-type destination-unreachable -j ACCEPT

  # Allow traffic through veth1 to physical namespace (for nginx proxy)
  iptables -A OUTPUT -o veth1 -d 10.10.13.37/31 -j ACCEPT
  iptables -A INPUT -i veth1 -s 10.10.13.37/31 -j ACCEPT

  # Allow established/related connections
  iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

  #
  # IPv6 Rules
  #

  # Flush existing rules
  ip6tables -F OUTPUT
  ip6tables -F INPUT

  # Default policy: DROP all IPv6 traffic
  ip6tables -P OUTPUT DROP
  ip6tables -P INPUT DROP
  ip6tables -P FORWARD DROP

  # Allow loopback
  ip6tables -A OUTPUT -o lo -j ACCEPT
  ip6tables -A INPUT -i lo -j ACCEPT

  # If IPv6 is configured on WireGuard, allow it
  if [ -n "$ipv6_address" ]; then
    ip6tables -A OUTPUT -o wg0 -j ACCEPT
    ip6tables -A INPUT -i wg0 -j ACCEPT

    # Allow ICMPv6 for diagnostics and Path MTU Discovery
    ip6tables -A OUTPUT -o wg0 -p icmpv6 --icmpv6-type echo-request -j ACCEPT
    ip6tables -A INPUT -i wg0 -p icmpv6 --icmpv6-type echo-reply -j ACCEPT
    ip6tables -A INPUT -i wg0 -p icmpv6 --icmpv6-type packet-too-big -j ACCEPT
  fi

  # Allow established/related connections
  ip6tables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  ip6tables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

  echo "Kill switch configured - all traffic blocked except through wg0"
}

setup_physical_namespace_firewall() {
  echo "Setting up physical namespace firewall..."

  # Get WireGuard endpoint
  wg_endpoint=$(wg show wg0 endpoints | awk '{print $2}' | cut -d: -f1)
  wg_port=$(wg show wg0 endpoints | awk '{print $2}' | cut -d: -f2)

  if [ -z "$wg_endpoint" ] || [ -z "$wg_port" ]; then
    echo "ERROR: Failed to get WireGuard endpoint. Cannot configure physical namespace firewall safely."
    exit 1
  fi

  # Default policies in physical namespace
  ip netns exec physical iptables -P OUTPUT DROP
  ip netns exec physical iptables -P INPUT DROP
  ip netns exec physical iptables -P FORWARD DROP

  # Allow loopback
  ip netns exec physical iptables -A OUTPUT -o lo -j ACCEPT
  ip netns exec physical iptables -A INPUT -i lo -j ACCEPT

  # Allow incoming connections to nginx reverse proxy
  ip netns exec physical iptables -A INPUT -i "$INT" -p tcp --dport "${WEBPROXY_PORT:-9091}" -j ACCEPT

  # Allow WireGuard UDP to endpoint
  ip netns exec physical iptables -A OUTPUT -o "$INT" -d "$wg_endpoint" -p udp --dport "$wg_port" -j ACCEPT
  ip netns exec physical iptables -A INPUT -i "$INT" -s "$wg_endpoint" -p udp --sport "$wg_port" -j ACCEPT

  # Allow veth2 traffic (from default namespace via nginx proxy)
  ip netns exec physical iptables -A INPUT -i veth2 -s 10.10.13.36/31 -j ACCEPT
  ip netns exec physical iptables -A OUTPUT -o veth2 -d 10.10.13.36/31 -j ACCEPT

  # Allow established connections
  ip netns exec physical iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
  ip netns exec physical iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

  # IPv6: Block everything in physical namespace
  ip netns exec physical ip6tables -P OUTPUT DROP
  ip netns exec physical ip6tables -P INPUT DROP
  ip netns exec physical ip6tables -P FORWARD DROP

  echo "Physical namespace firewall configured"
}

# Create a veth link pair, one interface in each namespace
ip link add veth1 type veth peer name veth2 netns physical

# Set their IPs, CIDR with only two addresses to limit ip route ranges
ip addr add 10.10.13.36/31 dev veth1
ip -n physical addr add 10.10.13.37/31 dev veth2

# Start the veth interfaces
ip link set veth1 up
ip -n physical link set veth2 up

# Apply kill switch rules (now veth1 exists)
setup_killswitch

# Apply physical namespace firewall rules
setup_physical_namespace_firewall

# Configure and start a reverse proxy in the physical namespace
WEBPROXY_PORT="${WEBPROXY_PORT:-9091}"
echo "Configuring nginx reverse proxy on port $WEBPROXY_PORT"
sed -i "s/listen [0-9]*;/listen $WEBPROXY_PORT;/" /opt/nginx/server.conf
ip netns exec physical nginx -c /opt/nginx/server.conf

# Make sure TRANSMISSION_HOME exists and create/update settings.json
mkdir -p "$TRANSMISSION_HOME"
python3 /opt/transmission/updateSettings.py /opt/transmission/default-settings.json ${TRANSMISSION_HOME}/settings.json || exit 1

# Support running Transmission as non-root (and set permissions on folders)
. /opt/transmission/userSetup.sh

exec su --preserve-environment ${RUN_AS} -s /bin/bash -c "/usr/bin/transmission-daemon --foreground -g ${TRANSMISSION_HOME}"
