#!/usr/bin/env bash
# Bring agent-01 / -02 online as inbound (JNLP) Jenkins agents.
#
# Run:  bash ~/dev/jenkins-mcp/scripts/bring-nodes-online.sh
#
# Needs on your Mac: sshpass (brew install sshpass), curl, jq.
# Reads Jenkins URL + admin + box SSH creds from ~/.config/jenkins-mcp/config.json.
#
# Boxes: polaris user is NOT in sudoers. We install a user-local Temurin 17
# under ~/.local/jdk-17 (Jenkins 2.479 agents need Java 17+; system Java is 8).
# Agent runs as a systemd --user service with linger enabled.
set -euo pipefail

CFG="$HOME/.config/jenkins-mcp/config.json"
JURL=$(jq -r '.url' "$CFG")
JUSER=$(jq -r '.username' "$CFG")
JPASS=$(jq -r '.password' "$CFG")
BOX_USER=$(jq -r '.ssh_boxes.username // "polaris"' "$CFG")
BOX_PASS=$(jq -r '.ssh_boxes.password' "$CFG")
NODES=( "agent-01:192.0.2.11" "agent-02:192.0.2.12" )

echo ">> Jenkins: $JURL   (as $JUSER)"
curl -fsS -u "$JUSER:$JPASS" "$JURL/api/json" >/dev/null \
  || { echo "!! Cannot reach Jenkins at $JURL — connect VPN first."; exit 1; }

for pair in "${NODES[@]}"; do
  NAME="${pair%%:*}"; IP="${pair##*:}"
  echo; echo "=== $NAME ($IP) ==="

  SECRET=$(curl -fsS -u "$JUSER:$JPASS" \
    "$JURL/computer/$NAME/jenkins-agent.jnlp" \
    | sed -n 's:.*<argument>\([a-f0-9]\{64\}\)</argument>.*:\1:p' | head -1)
  [ -n "$SECRET" ] || { echo "!! No secret for $NAME (is the node registered?)"; continue; }

  sshpass -p "$BOX_PASS" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 \
    "$BOX_USER@$IP" \
    "JURL='$JURL' NAME='$NAME' SECRET='$SECRET' bash -s" <<'REMOTE'
set -euo pipefail
cd "$HOME"

JDK_DIR="$HOME/.local/jdk-17"
JAVA="$JDK_DIR/bin/java"
if [ ! -x "$JAVA" ]; then
  echo "-- downloading Eclipse Temurin 17 (user-local, no sudo)"
  mkdir -p "$HOME/.local"
  TMP=$(mktemp -d)
  curl -fL --retry 3 -o "$TMP/jdk17.tar.gz" \
    "https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse?project=jdk"
  mkdir -p "$TMP/extract"
  tar -xzf "$TMP/jdk17.tar.gz" -C "$TMP/extract"
  SRC=$(find "$TMP/extract" -maxdepth 1 -type d -name 'jdk-17*' | head -1)
  rm -rf "$JDK_DIR"
  mv "$SRC" "$JDK_DIR"
  rm -rf "$TMP"
fi
"$JAVA" -version 2>&1 | head -1

mkdir -p "$HOME/jenkins-agent"
curl -fsS -o "$HOME/jenkins-agent/agent.jar" "$JURL/jnlpJars/agent.jar"

pkill -f "agent.jar" 2>/dev/null || true
sleep 1

mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/jenkins-agent.service" <<UNIT
[Unit]
Description=Jenkins inbound agent ($NAME)
After=network-online.target
[Service]
Environment=JAVA_HOME=%h/.local/jdk-17
ExecStart=%h/.local/jdk-17/bin/java -jar %h/jenkins-agent/agent.jar -url $JURL -name $NAME -secret $SECRET -workDir %h/jenkins-agent
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
  systemctl --user --no-pager status jenkins-agent.service | head -8 || true
else
  nohup "$JAVA" -jar "$HOME/jenkins-agent/agent.jar" \
    -url "$JURL" -name "$NAME" -secret "$SECRET" \
    -workDir "$HOME/jenkins-agent" >"$HOME/jenkins-agent/agent.log" 2>&1 &
  sleep 4; tail -5 "$HOME/jenkins-agent/agent.log" || true
fi
echo "-- $NAME agent launched"
REMOTE
done

echo; echo ">> Waiting 6s then checking node status..."
sleep 6
jenkins-mcp status 2>/dev/null || true
