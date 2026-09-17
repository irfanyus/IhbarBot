#!/bin/bash
# .app girişi: betiği terminalsiz çalıştırır, çıktıyı log'a yazar.
B="${1%/}"                                   # .app'in yolu
PROJE_KOK="$(dirname "$B")"
export PROJE_KOK
PN_BASLIK="$(basename "$B" .app)"
export PN_BASLIK

LOGDIR="$HOME/Desktop/Projects/.baslatici/log"
mkdir -p "$LOGDIR"
LOG="$LOGDIR/$(basename "$PROJE_KOK")-$PN_BASLIK.log"

# Her başlatmada baştan yaz; log dosyaları büyümesin.
printf '=== %s ===\n' "$(date '+%Y-%m-%d %H:%M:%S')" > "$LOG"
exec /bin/bash "$B/Contents/Resources/betik.sh" >>"$LOG" 2>&1
