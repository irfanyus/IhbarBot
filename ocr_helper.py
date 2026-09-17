import subprocess
import os
import re

# Dash-cam GPS bindirmesi genelde karenin alt şeridinde ve küçük punto olduğu için
# tam karede Vision OCR bazı parçaları düşürüyor (örn. 'E29.' kaybolup geriye yalnız
# '367887' kalıyor). Bu yüzden kareyi kırpıp büyüterek birkaç kez daha okutuyoruz.
# Sıra önemli: önce ham kare (mevcut davranış), sonra giderek agresifleşen varyantlar.
OCR_VARIANT_FILTERS = [
    None,  # ham kare
    "crop=iw/2:ih*0.12:0:ih*0.88,scale=iw*3:ih*3:flags=lanczos,eq=contrast=1.4",   # sol alt köşe, 3x
    "crop=iw:ih*0.12:0:ih*0.88,scale=iw*2:ih*2:flags=lanczos,eq=contrast=1.3",     # tüm alt şerit, 2x
    "crop=iw/2:ih*0.12:0:0,scale=iw*3:ih*3:flags=lanczos,eq=contrast=1.4",         # sol üst köşe (üstte yazan kameralar)
]


def _find_ffmpeg():
    """ffmpeg'i bilinen kurulum yollarında arar, bulamazsa PATH'e güvenir."""
    for path in ('/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg'):
        if os.path.exists(path):
            return path
    return 'ffmpeg'


def get_video_duration(video_path):
    """Videonun saniye cinsinden süresini döndürür; okunamazsa None."""
    ffprobe = _find_ffmpeg().replace('ffmpeg', 'ffprobe')
    try:
        out = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
            capture_output=True, text=True, check=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def apply_video_filter(image_path, output_image_path, vf):
    """Bir kareye ffmpeg video filtresi (kırpma/büyütme/kontrast) uygular."""
    try:
        cmd = [_find_ffmpeg(), '-y', '-i', image_path, '-vf', vf, output_image_path]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return os.path.exists(output_image_path)
    except Exception as e:
        print(f"[OCR] Kare ön işleme hatası: {e}")
        return False


def extract_frame_from_video(video_path, output_image_path, at_seconds=1):
    """
    Extracts a single frame at the given second of the video using ffmpeg.
    """
    ffmpeg_cmd = _find_ffmpeg()

    try:
        print(f"[OCR] ffmpeg ile videodan referans karesi çıkarılıyor ({at_seconds}. saniye)...")
        cmd = [
            ffmpeg_cmd, '-y',
            '-ss', str(at_seconds),
            '-i', video_path,
            '-vframes', '1',
            output_image_path
        ]
        # Run subprocess silently
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return os.path.exists(output_image_path)
    except Exception as e:
        print(f"[OCR] ffmpeg kare çıkarma hatası: {e}")
        return False

def run_vision_ocr(image_path):
    """
    Runs the native macOS Vision OCR Swift script on the given image.
    """
    swift_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ocr_helper.swift")
    if not os.path.exists(swift_script_path):
        return []
        
    try:
        print("[OCR] macOS Vision API ile metin taraması yapılıyor...")
        cmd = ['swift', swift_script_path, image_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Split by newlines and filter out empty strings
        lines = [line.strip() for line in result.stdout.split('\n') if line.strip()]
        return lines
    except Exception as e:
        print(f"[OCR] Swift OCR hatası: {e}")
        return []

def parse_coordinates(lines):
    """
    Extracts latitude and longitude from recognized text lines.
    
    Handles tricky OCR dash-cam output such as:
      - Spaces within decimals:  'N40. 933167'  -> 40.933167
      - Partial matches on one line + decimal on next:
          line i:   'E29'
          line i+1: '430-1599'   -> 29.430159
      - Normal single-line format: 'N40.933024 E29.301933'
    """
    lat = None
    lon = None

    # --- Step 1: fix 'digit dot space digit' artifacts across joined text ---
    # Join all lines so we can also catch cross-line number+decimal situations
    joined = " ".join(lines)
    joined = re.sub(r'(\d+)\.\s+(\d+)', r'\1.\2', joined)

    # --- Step 2: standard single-token match (works after space-removal fix) ---
    coord_pattern = re.compile(r'([NSEW])\s*(\d{1,3}\.\d+)', re.IGNORECASE)
    for m in coord_pattern.finditer(joined):
        direction = m.group(1).upper()
        value = float(m.group(2))
        if direction in ('N', 'S') and lat is None:
            lat = value if direction == 'N' else -value
        elif direction in ('E', 'W') and lon is None:
            lon = value if direction == 'E' else -value

    # --- Step 2b: 'E29\u2122 367887' – yön+tam kısım ile ondalık arasına OCR çöpü girmiş ---
    # (Vision, bindirmedeki '.' karakterini sık sık '\u2122', '~', '-' gibi okuyor.)
    if lat is None or lon is None:
        for m in re.finditer(r'([NSEW])\s*(\d{1,3})[^\dA-Za-z]{1,3}\s*(\d{4,8})\b', joined, re.IGNORECASE):
            direction = m.group(1).upper()
            value = float(f"{m.group(2)}.{m.group(3)}")
            if direction in ('N', 'S') and lat is None:
                lat = value if direction == 'N' else -value
            elif direction in ('E', 'W') and lon is None:
                lon = value if direction == 'E' else -value

    # --- Step 3: fallback – 'E29' on one line, '430-1599' on next ---
    if lat is None or lon is None:
        for i, line in enumerate(lines):
            # Satırın başında/sonunda OCR çöpü olabilir: '_E29', 'E29\u2122', 'N40 .'
            m = re.match(r'^[^\dA-Za-z]*([NSEW])\s*(\d{1,3})[^\d]*$', line.strip(), re.IGNORECASE)
            if m and i + 1 < len(lines):
                direction = m.group(1).upper()
                integer_part = m.group(2)
                next_line = lines[i + 1].strip()
                # Next line might look like '430-1599' (OCR '-' or '.' as separator)
                dm = re.match(r'^(\d+)[.\-]?(\d*)', next_line)
                if dm:
                    dec = dm.group(1) + (dm.group(2) or '')
                    try:
                        value = float(f"{integer_part}.{dec}")
                        if direction in ('N', 'S') and lat is None:
                            lat = value if direction == 'N' else -value
                        elif direction in ('E', 'W') and lon is None:
                            lon = value if direction == 'E' else -value
                    except ValueError:
                        pass

    # OCR çöpünden gelen saçma değerleri ele: enlem ±90, boylam ±180 dışı olamaz.
    if lat is not None and abs(lat) > 90:
        lat = None
    if lon is not None and abs(lon) > 180:
        lon = None

    return lat, lon

def parse_datetime(lines):
    """
    Extracts date and time from recognized text lines.
    """
    # Match patterns like DD/MM/YYYY HH:MM:SS, DD.MM.YYYY HH:MM or similar
    dt_pattern = r'(\d{2}[/.-]\d{2}[/.-]\d{4}|\d{4}[/.-]\d{2}[/.-]\d{2})\s+(\d{2}:\d{2}(:\d{2})?)'

    # OCR tarih ile saati ayrı satırlara bölebiliyor ('04/07/2026' + '10:22:04'),
    # bu yüzden satır satır değil, tüm satırları birleştirip tek metinde arıyoruz.
    # Ayrıca ayırıcıların etrafına boşluk sızabiliyor: '06/07 /2026 08: 33:25'.
    joined = " ".join(lines)
    joined = re.sub(r'\s*([/.:])\s*', r'\1', joined)

    dt_match = re.search(dt_pattern, joined)
    if dt_match:
        date_str = dt_match.group(1)
        time_str = dt_match.group(2)

        # Normalize separators to dots
        date_str = date_str.replace('/', '.').replace('-', '.')
        # Only keep HH:MM
        time_parts = time_str.split(':')
        time_str = f"{time_parts[0]}:{time_parts[1]}"
        return f"{date_str} {time_str}"

    return None

def ocr_frame_variants(image_path, work_dir=None):
    """
    Bir kareyi önce ham, sonra kırpılmış/büyütülmüş varyantlarıyla OCR'dan geçirir.
    Her varyantın satır listesini tek tek üretir (generator) — çağıran taraf aradığını
    bulduğunda kalan varyantları çalıştırmadan çıkabilir.
    """
    work_dir = work_dir or os.path.dirname(os.path.abspath(image_path))
    for idx, vf in enumerate(OCR_VARIANT_FILTERS):
        if vf is None:
            target = image_path
        else:
            target = os.path.join(work_dir, f"temp_ocr_variant_{idx}.png")
            print(f"[OCR] Bindirme okunamadı, kare kırpılıp büyütülerek yeniden deneniyor (varyant {idx})...")
            if not apply_video_filter(image_path, target, vf):
                continue
        try:
            yield run_vision_ocr(target)
        finally:
            if target != image_path and os.path.exists(target):
                try:
                    os.remove(target)
                except OSError:
                    pass


def read_metadata_from_image(image_path, work_dir=None, lat=None, lon=None, dt_str=None):
    """
    Tek bir görseli OCR varyantlarından geçirip eksik koordinat/tarih alanlarını doldurur.
    Zaten bilinen (lat, lon, dt_str) değerlerini olduğu gibi korur; yalnızca None olanları
    doldurmaya çalışır. Videonun kare kare taraması da, hazır bir fotoğraf da bunu kullanır.
    """
    for lines in ocr_frame_variants(image_path, work_dir=work_dir):
        if not lines:
            continue
        if lat is None or lon is None:
            new_lat, new_lon = parse_coordinates(lines)
            lat = lat if lat is not None else new_lat
            lon = lon if lon is not None else new_lon
        if dt_str is None:
            dt_str = parse_datetime(lines)
        if lat is not None and lon is not None and dt_str:
            break
    return lat, lon, dt_str


def analyze_image_metadata(image_path):
    """
    Hazır bir dash-cam fotoğrafından koordinat ve tarih/saati okur.
    Dash-cam görselinde de GPS bindirmesi ve tarih basılı olduğu için, video yoksa
    doğrudan bu görsel taranabilir. Çıktı biçimi analyze_video_metadata ile aynıdır:
    ((lat, lon), dt_str).
    """
    work_dir = os.path.dirname(os.path.abspath(image_path))
    lat, lon, dt_str = read_metadata_from_image(image_path, work_dir=work_dir)
    return (lat, lon), dt_str


def analyze_video_metadata(video_path):
    """
    Extracts coordinates and datetime from a video via frame OCR.
    Tries several timestamps: GPS overlay may be missing on early frames
    (no GPS fix yet), so keep sampling until both fields are found.
    Her karede ayrıca birkaç ön işleme varyantı denenir; küçük punto bindirmede
    Vision tam kareden 'E29.' gibi parçaları düşürebiliyor (bkz. OCR_VARIANT_FILTERS).
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    temp_image = os.path.join(base_dir, "temp_ocr_frame.png")

    lat, lon, dt_str = None, None, None

    # Videodan uzun bir saniye istenirse ffmpeg boş çıktı üretiyor; 3 sn'lik bir klipte
    # 5. saniyeyi istemek hiç kare alamamak demek. Süreyi bilip listeyi kırpıyoruz.
    sample_seconds = [1, 3, 5, 10, 20, 40]
    duration = get_video_duration(video_path)
    if duration:
        sample_seconds = [t for t in sample_seconds if t < duration] or [0]

    for ts in sample_seconds:
        if not extract_frame_from_video(video_path, temp_image, at_seconds=ts):
            break  # video bitti / kare çıkarılamadı

        lat, lon, dt_str = read_metadata_from_image(temp_image, base_dir, lat, lon, dt_str)

        if lat is not None and lon is not None and dt_str:
            break
        print(f"[OCR] {ts}. saniyede eksik bilgi var, sonraki kare deneniyor...")

    # Clean up temp image
    if os.path.exists(temp_image):
        try:
            os.remove(temp_image)
        except:
            pass

    return (lat, lon), dt_str
