#!/usr/bin/env bash
set -euxo pipefail

REPO_URL="https://github.com/rebanto/knowledge-graph-engine.git"
APP_DIR="/opt/kgre"
APP_USER="ubuntu"

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y ca-certificates curl gnupg git lsb-release iptables-persistent netfilter-persistent

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

if id "${APP_USER}" >/dev/null 2>&1; then
  usermod -aG docker "${APP_USER}"
fi

if [ ! -f /swapfile ]; then
  fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
  chmod 600 /swapfile
  mkswap /swapfile
fi

if ! swapon --show=NAME | grep -qx /swapfile; then
  swapon /swapfile
fi

grep -qE '^/swapfile\s+' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
cat >/etc/sysctl.d/99-kgre.conf <<'EOF'
vm.swappiness=10
EOF
sysctl --system

mkdir -p "${APP_DIR}"
if [ ! -d "${APP_DIR}/.git" ]; then
  rm -rf "${APP_DIR}"
  git clone "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" remote set-url origin "${REPO_URL}"
  git -C "${APP_DIR}" fetch --all --prune
fi

if id "${APP_USER}" >/dev/null 2>&1; then
  chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"
fi

# OCI Ubuntu images can ship restrictive INPUT rules. Opening 80/443 is safe on
# AWS too; cloud security groups / security lists still decide public exposure.
if iptables -S INPUT | grep -Eq 'DROP|REJECT|-P INPUT DROP'; then
  echo "Restrictive IPv4 INPUT rules detected; opening HTTP/HTTPS."
else
  echo "No restrictive IPv4 INPUT policy detected; ensuring HTTP/HTTPS are open."
fi
iptables -C INPUT -p tcp --dport 80 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT
iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
netfilter-persistent save || true

cat <<'EOF'

KGRE bootstrap complete.
Next steps:
  cd /opt/kgre
  cp .env.prod.example .env
  nano .env
  bash scripts/aws/deploy.sh
EOF
