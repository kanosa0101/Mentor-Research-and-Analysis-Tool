#!/bin/sh
set -eu
install -d -o root -g mentor-assistant -m 750 /opt/mentor-assistant/var/tls
install -o root -g mentor-assistant -m 640 /opt/mentor-assistant/var/certbot/live/8.213.137.82/fullchain.pem /opt/mentor-assistant/var/tls/fullchain.pem
install -o root -g mentor-assistant -m 640 /opt/mentor-assistant/var/certbot/live/8.213.137.82/privkey.pem /opt/mentor-assistant/var/tls/privkey.pem
systemctl try-restart mentor-https.service
