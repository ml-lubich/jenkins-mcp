#!/usr/bin/env bash
# Bring svl-dc-dev-test-01 / -02 online as inbound (JNLP) Jenkins agents.
#
# Run it yourself:   bash ~/dev/jenkins-mcp/scripts/bring-nodes-online.sh
#
# Needs on your Mac: sshpass (brew install sshpass), curl, jq.
# Reads Jenkins URL + admin creds from ~/.config/jenkins-mcp/config.json.
# SSHes to each box with polaris/polaris123, installs Java if missing,
# grabs that node's agent secret from Jenkins, launches agent.jar under a
# systemd --user service so it survives logout/reboot, then verifies online.
set -euo pipefail

CFG="$HOME/.config/jenkins-mcp/config.json"
JURL=$(jq -r '.url'      "$CFG")   # e.g. http://dev-jenkins:8080
JUSER=$(jq -r '.username' "$CFG")
JPASS=$(jq -r '.password' "$CFG")

BOX_USER="polaris"
BOX_PASS="polaris123"
NODES=( "svl-dc-dev-test-01:10.55.110.151" "svl-dc-dev-test-02:10.55.110.152" )

echo ">> Jenkins: $JURL   (as $JUSER)"
curl -fsS -u "$JUSER:$JPASS" "$JURL/api/json" >/dev/null \
  || { echo "!! Cannot reach Jenkins at $JURL — connect VPN first."; exit 1; }

for pair in "${NODES[@]}"; do
  NAME="${pair%%:*}"; IP="${pair##*:}"
  echo; echo "=== $NAME ($IP) ==="

  # Per-node inbound-agent secret from Jenkins.
  SECRET=$(curl -fsS -u "$JUSER:$JPASS" \
    "$JURL/computer/$NAME/jenkins-agent.jnlp" \
    | sed -n 's:.*<argument>\([a-f0-9]\{64\}\)</argument>.*:\1:p' | head -1)
  [ -n "$SECRET" ] || { echo "!! No secret for $NAME (is the node registered?)"; continue; }

  sshpass -p "$BOX_PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=8 \
    "$BOX_USER@$IP" \
    "JURL='$JURL' NAME='$NAME' SECRET='$SECRET' bash -s" <<'REMOTE'
set -e
# Java (agent needs 11+). Try apt, else dnf, else assume present.
# Java (agent runtime) AND git (checkouts fail without it — this is what breaks the builds).
NEED=""
command -v java >/dev/null 2>&1 || NEED="$NEED java"
command -v git  >/dev/null 2>&1 || NEED="$NEED git"
if [ -n "$NEED" ]; then
  echo "-- installing:$NEED"
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -qq
    [ -z "${NEED##* java*}" ] && sudo apt-get install -y -qq default-jre-headless
    [ -z "${NEED##* git*}"  ] && sudo apt-get install -y -qq git
  elif command -v dnf >/dev/null 2>&1; then
    [ -z "${NEED##* java*}" ] && sudo dnf install -y -q java-17-openjdk-headless
    [ -z "${NEED##* git*}"  ] && sudo dnf install -y -q git
  else
    echo "!! No apt/dnf — install$NEED manually."; exit 1
  fi
fi
mkdir -p "$HOME/jenkins-agent"
curl -fsS -o "$HOME/jenkins-agent/agent.jar" "$JURL/jnlpJars/agent.jar"

# Persistent systemd --user service (survives logout with linger).
mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/jenkins-agent.service" <<UNIT
[Unit]
Description=Jenkins inbound agent ($NAME)
After=network-online.target
[Service]
ExecStart=/usr/bin/java -jar %h/jenkins-agent/agent.jar \
  -url $JURL -name $NAME -secret $SECRET -workDir %h/jenkins-agent
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
UNIT

if command -v systemctl >/dev/null 2>&1; then
  loginctl enable-linger "$USER" >/dev/null 2>&1 || true
  systemctl --user daemon-reload
  systemctl --user enable --now jenkins-agent.service
  sleep 4
  systemctl --user --no-pager status jenkins-agent.service | head -5 || true
else
  # No systemd: fall back to nohup.
  pkill -f "agent.jar.*$NAME" 2>/dev/null || true
  nohup java -jar "$HOME/jenkins-agent/agent.jar" \
    -url "$JURL" -name "$NAME" -secret "$SECRET" \
    -workDir "$HOME/jenkins-agent" >"$HOME/jenkins-agent/agent.log" 2>&1 &
  sleep 4; tail -3 "$HOME/jenkins-agent/agent.log" || true
fi
echo "-- $NAME agent launched"
REMOTE
done

echo; echo ">> Waiting 6s then checking node status..."
sleep 6
jenkins-mcp status 2>/dev/null || .venv/bin/jenkins-mcp status
