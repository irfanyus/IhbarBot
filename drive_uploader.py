"""
Dash-cam videosunu Google Drive'a yükleyip paylaşılabilir link üretir.

Site ihbara video eklenmesine izin vermiyor (bkz. CLAUDE.md — video sessizce
düşüyor), bu yüzden videoyu Drive'a koyup linkini ihbar açıklamasına yazıyoruz.

Drive erişimi için `rclone` kullanılıyor: kendi doğrulanmış OAuth istemcisi
olduğu için Google Cloud Console'da proje/anahtar oluşturmaya gerek kalmıyor ve
jeton kısa sürede geçersizleşmiyor. Kurulum tek seferlik:

    brew install rclone          # kurulu
    rclone config create gdrive drive   # tarayıcıda Google girişi

Yalnızca yüklenen dosya paylaşıma açılıyor; klasörün kendisi gizli kalıyor, yani
bir ihbarın linki diğer ihbarların videolarını göstermiyor.
"""

import json
import os
import re
import shutil
import subprocess

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _config(key, fallback):
    """config.json'daki Drive ayarını okur; dosya/alan yoksa varsayılana düşer."""
    try:
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            return json.load(fh).get(key) or fallback
    except Exception:
        return fallback


# Klasör adını değil kimliğini kullanıyoruz: Drive'da klasör yeniden
# adlandırılsa ya da aynı adda ikinci bir klasör açılsa da yükleme doğru yere gider.
DEFAULT_FOLDER_ID = _config("drive_klasor_id", "")
DEFAULT_REMOTE = _config("drive_remote", "gdrive")

UPLOAD_TIMEOUT_SEC = 600  # 25 MB'lik bir klip için fazlasıyla yeterli


class DriveUploadError(Exception):
    """Yükleme ya da link üretimi başarısız oldu."""


def _rclone_path():
    return shutil.which("rclone") or "/opt/homebrew/bin/rclone"


def is_available():
    """rclone kurulu mu?"""
    return os.path.exists(_rclone_path()) or shutil.which("rclone") is not None


def is_configured(remote=DEFAULT_REMOTE):
    """rclone'da Drive bağlantısı tanımlı mı? (tek seferlik `rclone config`)"""
    if not is_available():
        return False
    try:
        out = subprocess.run([_rclone_path(), "listremotes"],
                             capture_output=True, text=True, timeout=15)
        return f"{remote}:" in out.stdout
    except Exception:
        return False


def setup_hint(remote=DEFAULT_REMOTE):
    """Kurulum eksikse kullanıcıya gösterilecek tek satırlık talimat."""
    if not is_available():
        return "Drive yüklemesi için önce rclone gerekiyor:  brew install rclone"
    return (f"Drive bağlantısı henüz kurulmamış. Terminalde bir kez şunu çalıştır "
            f"(tarayıcıda Google girişi açılır):  rclone config create {remote} drive")


def _run(args, timeout):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise DriveUploadError((result.stderr or result.stdout).strip() or
                               f"rclone {args[1]} başarısız (kod {result.returncode})")
    return result.stdout.strip()


def upload_and_get_link(video_path, remote=DEFAULT_REMOTE, folder_id=DEFAULT_FOLDER_ID):
    """
    Videoyu Drive klasörüne yükler ve 'bağlantıya sahip herkes' linkini döndürür.
    Başarısızlıkta DriveUploadError fırlatır — çağıran taraf ihbarı linksiz sürdürebilir.
    """
    if not video_path or not os.path.exists(video_path):
        raise DriveUploadError(f"Video bulunamadı: {video_path}")
    if not is_configured(remote):
        raise DriveUploadError(setup_hint(remote))
    if not folder_id:
        raise DriveUploadError("config.json'da 'drive_klasor_id' tanımlı değil.")

    rclone = _rclone_path()
    root = ["--drive-root-folder-id", folder_id]
    name = os.path.basename(video_path)

    size_mb = os.path.getsize(video_path) / 1024 / 1024
    print(f"[DRIVE] Video yükleniyor: {name} ({size_mb:.1f} MB)...")
    _run([rclone, "copyto", *root, os.path.abspath(video_path), f"{remote}:{name}"],
         timeout=UPLOAD_TIMEOUT_SEC)

    print("[DRIVE] Paylaşım linki alınıyor...")
    link = _run([rclone, "link", *root, f"{remote}:{name}"], timeout=120)
    if not link.startswith("http"):
        raise DriveUploadError(f"Beklenmeyen link çıktısı: {link!r}")

    link = _normalize_link(link)
    print(f"[DRIVE] Hazır: {link}")
    return link


def _normalize_link(link):
    """
    rclone linki 'drive.google.com/open?id=<id>' biçiminde veriyor. Çalışıyor ama
    ihbarı okuyan memura Drive'ın kendi tanıdık biçimini göstermek daha iyi; ayrıca
    '?' ve '=' içermediği için sitenin karakter filtresine hiç takılmıyor.
    """
    match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", link)
    if match:
        return f"https://drive.google.com/file/d/{match.group(1)}/view"
    return link


# ── Linki sitenin harf dönüşümlerine karşı zırhlama ───────────────────────────
# Sitenin açıklama alanı yazılan her şeyi anında toLocaleUpperCase("tr") ile
# büyütüyor; alandan çıkıldığında da metni POST /api/detect-url'e yollayıp dönen
# adresi (küçük harfe çevrilmiş halde) metnin içine geri yazıyor. Yani açıklamaya
# yazdığımız her adres "büyüt -> küçült" turundan geçiyor. Baştan sona küçük
# harfli bir adres bu turdan aynen çıkıyor, ama Drive dosya kimliği büyük/küçük
# harf duyarlı: 1Oy_GbhbTNQn... -> 1OY_GBHBTNQN... -> 1oy_gbhbtnqn... ve link
# artık açılmıyor. Kimliğin hangi harfinin başta büyük olduğu da geri
# döndürülemiyor, yani elle "İ"leri "I" yapmak da işe yaramıyor.
#
# Çözüm: kimlikteki BÜYÜK harfleri yüzde kodlamasına çevirmek. Yüzde
# kodlamasının onaltılık basamakları büyük/küçük harf duyarsız ("%4F" de "%4f"
# de 'O' demek), dolayısıyla tur kimliğe zarar veremiyor. Adresin geri kalanı
# (drive.google.com/file/d/.../view) zaten baştan sona küçük harfli olduğu için
# turdan aynen çıkıyor. Google bu biçimi normal link gibi açıyor (10.09.2026'da
# tarayıcıda doğrulandı).
def armor_link_for_site(link):
    """Drive linkini sitenin açıklama alanına dayanıklı biçimde yazar."""
    match = re.fullmatch(r"https://drive\.google\.com/file/d/([A-Za-z0-9_-]+)/view", link or "")
    if not match:
        return link
    file_id = match.group(1)
    armored = "".join(f"%{ord(c):02X}" if c.isupper() else c for c in file_id)
    return f"https://drive.google.com/file/d/{armored}/view"


def append_link_to_description(description, link):
    """
    İhbar açıklamasının sonuna video linkini ekler.

    Site açıklamada yalnızca belirli karakterlere izin veriyor (bkz.
    form_filler.DESCRIPTION_ALLOWED_RE); ':' '/' '.' '-' '_' '?' '=' '&' izinli
    olduğu için Drive linkleri olduğu gibi geçiyor.
    """
    if not link:
        return description
    # Yazım Türkçe kurallarına uygun olmalı: site metni tr-büyük harfe çeviriyor,
    # yani "kaydi" -> "KAYDİ", "ayrica" -> "AYRİCA" gibi bozuk çıktılar veriyor.
    note = (f"Olayın video kaydı: {armor_link_for_site(link)} "
            f"(talep halinde ayrıca iletilebilir)")
    return f"{description.rstrip()} {note}" if description else note
