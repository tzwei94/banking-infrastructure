#!/usr/bin/env bash
set -euo pipefail
# Run as root through SSM; token is read silently, never supplied in user data.
[[ $EUID == 0 ]] || { echo 'Run through an administrative SSM session' >&2; exit 1; }
repo=${1:?Usage: register-runner.sh OWNER/REPO app-or-deploy VERSION SHA256}
kind=${2:?}; version=${3:?}; checksum=${4:?}
[[ $repo =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ && $kind =~ ^(app|deploy)$ && $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $checksum =~ ^[a-f0-9]{64}$ ]] || exit 2
# /var/lock points into volatile /run on AL2023. Recreate the shared
# publication/deployment lock at every boot, before runner services start.
cat > /etc/tmpfiles.d/banking-runner.conf <<'EOF'
d /run/lock/banking 1777 root root -
f /run/lock/banking/host.lock 0666 root root -
EOF
chmod 644 /etc/tmpfiles.d/banking-runner.conf
systemd-tmpfiles --create /etc/tmpfiles.d/banking-runner.conf
user="runner-$kind"; destination="/home/$user/actions-runner"
install -d -o "$user" -g "$user" -m 700 "$destination"
archive=$(mktemp)
trap 'rm -f "$archive"; unset token' EXIT
curl --fail --silent --show-error --location "https://github.com/actions/runner/releases/download/v$version/actions-runner-linux-x64-$version.tar.gz" -o "$archive"
printf '%s  %s\n' "$checksum" "$archive" | sha256sum -c -
tar xzf "$archive" -C "$destination"
chown -R "$user:$user" "$destination"
cd "$destination"
# GitHub's installer does not recognize AL2023 (no /etc/redhat-release).
# Install native runtime libraries without modifying the OS identification.
. /etc/os-release
if [[ ${ID:-} == amzn && ${VERSION_ID:-} == 2023 ]]; then
  dnf install -y glibc libgcc ca-certificates openssl-libs libstdc++ libicu tzdata krb5-libs zlib
else
  ./bin/installdependencies.sh
fi
# Fail before requesting a token if the bundled runtime cannot start.
sudo -u "$user" ./bin/Runner.Listener --version
read -rsp 'Short-lived repository runner registration token: ' token
printf '\n'
# GitHub runner requires a token argument; avoid shell tracing and shared untrusted users.
sudo -u "$user" "$destination/config.sh" --unattended --url "https://github.com/$repo" --token "$token" --name "banking-$kind" --labels "banking-$kind" --work _work
unset token
cd "$destination"
./svc.sh install "$user"
./svc.sh start
