#!/bin/bash
set -euo pipefail
# Amazon Linux 2023, x86_64. No registration credentials in user data/state.
dnf install -y docker git jq unzip util-linux java-25-amazon-corretto-devel maven awscli-2 python3
systemctl enable --now docker
install -d -m 1777 /var/lock/banking
for user in runner-app runner-deploy; do
  id "$user" &>/dev/null || useradd -m "$user"
  usermod -aG docker "$user"
done
# A shared Docker socket makes both users trusted administrators of this host.
# Restrict both services to protected repositories; never schedule PR code here.
touch /var/lock/banking/host.lock
chmod 666 /var/lock/banking/host.lock
