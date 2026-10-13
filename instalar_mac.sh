#!/bin/bash
# Instala (ou reinstala) a sincronização iCloud -> GitHub no launchd do macOS.
# Roda o sync_icloud.py a cada 15 minutos e ao ligar o Mac.
#
# O macOS não deixa processos em segundo plano lerem o iCloud Drive. Por isso o
# script roda dentro de um pequeno app ("MW Instagram Sync"): na primeira vez o
# macOS pergunta se ele pode acessar o iCloud Drive; clique em Permitir.
# Para desinstalar: ./instalar_mac.sh --remover
set -euo pipefail

LABEL="com.mwcapital.instagram-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/mw-instagram-sync.log"
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/MW Instagram Sync.app"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

if [ "${1:-}" = "--remover" ]; then
  rm -f "$PLIST"
  rm -rf "$APP"
  echo "Sincronização removida."
  exit 0
fi

mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Applications"
rm -rf "$APP"
osacompile -o "$APP" -e "try
  do shell script \"export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; /usr/bin/python3 '$DIR/sync_icloud.py' >> '$LOG' 2>&1\"
end try"
# roda sem ícone no Dock
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/open</string>
    <string>-g</string>
    <string>$APP</string>
  </array>
  <key>StartInterval</key><integer>900</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF

launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Sincronização instalada. Log: $LOG"
