#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $EUID -eq 0 ]]
PREPARED="$(realpath "${1:?prepared configuration directory}")"
BINARY="$(realpath "${2:?built authentication binary}")"
SERVICE="${AUTH_SERVICE:-auth-service}"
SERVICE_USER="${AUTH_SERVICE_USER:-auth-service}"
CONFIG="${AUTH_CONFIG:-/etc/auth-service/configuration.yml}"
INSTALLED_BINARY="${AUTH_BINARY:-/opt/auth-service/authelia}"
STATE="${AUTH_STATE_DIR:-/var/lib/auth-service}"
UNIT="/etc/systemd/system/${SERVICE}.service.d/email-login.conf"
BACKUP_ROOT="${AUTH_BACKUP_DIR:-/var/backups/auth-service}"
mkdir -p "$BACKUP_ROOT"
BACKUP="$(mktemp -d "$BACKUP_ROOT/email-login-XXXXXXXX")"
cp -a "$CONFIG" "$BACKUP/configuration.yml"
cp -a "$INSTALLED_BINARY" "$BACKUP/authelia"
[[ ! -f "$UNIT" ]] || cp -a "$UNIT" "$BACKUP/email-login.conf"
[[ ! -f "$STATE/users.yml" ]] || cp -a "$STATE/users.yml" "$BACKUP/users.yml"
stopped=false
rollback() {
  result=$?
  trap - ERR
  set +e
  systemctl stop "$SERVICE"
  cp -a "$BACKUP/configuration.yml" "$CONFIG"
  cp -a "$BACKUP/authelia" "$INSTALLED_BINARY"
  if [[ -f "$BACKUP/email-login.conf" ]]; then cp -a "$BACKUP/email-login.conf" "$UNIT"; else rm -f -- "$UNIT"; fi
  [[ ! -f "$BACKUP/users.yml" ]] || cp -a "$BACKUP/users.yml" "$STATE/users.yml"
  if [[ -f "$BACKUP/database.sqlite3" ]]; then
    python3 - "$BACKUP/database.sqlite3" "$STATE/database.sqlite3" <<'PY'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
PY
  fi
  systemctl daemon-reload
  systemctl start "$SERVICE"
  echo 'Authentication deployment failed and rolled back; see private backup.' >&2
  exit "$result"
}
trap rollback ERR
systemctl stop "$SERVICE"
python3 - "$STATE/database.sqlite3" "$BACKUP/database.sqlite3" <<'PY'
import sqlite3,sys
with sqlite3.connect(sys.argv[1]) as source, sqlite3.connect(sys.argv[2]) as target:
    source.backup(target)
PY
install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 0600 "$PREPARED/users.yml" "$STATE/users.yml"
install -o root -g "$SERVICE_USER" -m 0640 "$PREPARED/configuration.yml" "$CONFIG"
install -o root -g root -m 0755 "$BINARY" "$INSTALLED_BINARY"
mkdir -p "$(dirname "$UNIT")"
cat > "$UNIT" <<UNIT
[Service]
Environment=AUTH_LOGIN_MODE=email_otp
Environment=AUTH_EMAIL_OTP_STATE=$STATE/email-login-state.json
UNIT
python3 - "$PREPARED/registration.json" "$INSTALLED_BINARY" "$CONFIG" <<'PY'
import json,subprocess,sys
r=json.load(open(sys.argv[1]))
p=subprocess.run([sys.argv[2],'storage','user','identifiers','add',r['username'],
                  '--identifier',r['subject'],'--config',sys.argv[3]],capture_output=True)
if p.returncode: raise SystemExit('Authentication identity registration failed; details suppressed.')
PY
"$INSTALLED_BINARY" validate-config --config "$CONFIG" > "$BACKUP/validation.log" 2>&1
systemctl daemon-reload
systemctl start "$SERVICE"
for attempt in {1..30}; do
  if curl -fsS "${AUTH_HEALTH_URL:-http://127.0.0.1:9091/auth/api/email-otp/configuration}" | python3 -c 'import json,sys; assert json.load(sys.stdin)["data"]["enabled"] is True' 2>/dev/null; then
    systemctl is-active --quiet "$SERVICE"
    trap - ERR
    echo 'AUTH_EMAIL_LOGIN_DEPLOYED'
    exit 0
  fi
  sleep 1
done
false
