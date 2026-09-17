#!/bin/bash
# İhbarBot — Tkinter penceresi açılır. Kapatmak için pencereyi kapat.
source "$HOME/Desktop/Projects/.baslatici/ortak.sh"
cd "${PROJE_KOK:-$(dirname "$0")}" || exit 1

if [ ! -d venv ]; then
  hata_bitir "venv klasörü yok. Kurulum için OKUBENI dosyasına bak."
fi

source venv/bin/activate
python3 app.py || hata_bitir "İhbarBot kapandı.
Ayrıntı için: Projects/.baslatici/log/IhbarBot-İhbarBot.log"
