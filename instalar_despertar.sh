#!/bin/bash
# Programa o Mac para acordar sozinho nos horários dos posts (09:01, 12:01 e
# 19:01), para a sincronização disparar a publicação mesmo com o Mac dormindo.
#
# O macOS só aceita despertares avulsos, então isto instala uma tarefa do
# sistema que, todo dia, agenda os despertares de hoje e de amanhã.
#
# Precisa de senha de administrador:   sudo ./instalar_despertar.sh
# Para remover:                         sudo ./instalar_despertar.sh --remover
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Rode com sudo: sudo $0 $*"
  exit 1
fi

LABEL="com.mwcapital.instagram-wake"
PLIST="/Library/LaunchDaemons/$LABEL.plist"
DIR="/Library/Application Support/MWInstagram"
SCRIPT="$DIR/agendar_despertar.sh"

launchctl bootout "system/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "--remover" ]; then
  rm -f "$PLIST"
  rm -rf "$DIR"
  echo "Despertar automático removido. (Despertares já agendados para hoje/amanhã ainda acontecem.)"
  exit 0
fi

mkdir -p "$DIR"
cat > "$SCRIPT" <<'EOF'
#!/bin/bash
# Agenda os despertares de hoje e amanhã que ainda não estão agendados.
now=$(date +%s)
for offset in 0 1; do
  for hora in 09:01:00 12:01:00 19:01:00; do
    dia=$(date -v+${offset}d +%m/%d/%Y)
    quando=$(date -j -f "%m/%d/%Y %H:%M:%S" "$dia $hora" +%s)
    [ "$quando" -le "$now" ] && continue
    pmset -g sched | grep -q "wake at $dia $hora" && continue
    pmset schedule wake "$(date -j -f %s "$quando" "+%m/%d/%y %H:%M:%S")"
  done
done
EOF
chmod 755 "$SCRIPT"
chown -R root:wheel "$DIR"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>$SCRIPT</string></array>
  <key>RunAtLoad</key><true/>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>5</integer></dict>
    <dict><key>Hour</key><integer>12</integer><key>Minute</key><integer>5</integer></dict>
  </array>
</dict>
</plist>
EOF
chown root:wheel "$PLIST"
chmod 644 "$PLIST"
launchctl bootstrap system "$PLIST"
sleep 2
echo "Despertar automático instalado. Próximos despertares:"
pmset -g sched | grep -E "(09|12|19):01:00" || echo "(nenhum ainda, confira com: pmset -g sched)"
