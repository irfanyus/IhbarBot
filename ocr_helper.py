import subprocess
import os
import re

def extract_frame_from_video(video_path, output_image_path, at_seconds=1):
    """
    Extracts a single frame at the given second of the video using ffmpeg.
    """
    # Look for ffmpeg in common paths, default to 'ffmpeg' if not found
    ffmpeg_paths = ['/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', 'ffmpeg']
    ffmpeg_cmd = 'ffmpeg'
    for path in ffmpeg_paths:
        if os.path.exists(path) or path == 'ffmpeg':
            ffmpeg_cmd = path
            if path != 'ffmpeg':
                break
                
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

    # --- Step 3: fallback – 'E29' on one line, '430-1599' on next ---
    if lat is None or lon is None:
        for i, line in enumerate(lines):
            m = re.match(r'^([NSEW])\s*(\d{1,3})\s*$', line.strip(), re.IGNORECASE)
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

def analyze_video_metadata(video_path):
    """
    Extracts coordinates and datetime from a video via frame OCR.
    Tries several timestamps: GPS overlay may be missing on early frames
    (no GPS fix yet), so keep sampling until both fields are found.
    """
    temp_image = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_ocr_frame.png")

    lat, lon, dt_str = None, None, None

    for ts in (1, 3, 5, 10, 20, 40):
        if not extract_frame_from_video(video_path, temp_image, at_seconds=ts):
            break  # video bitti / kare çıkarılamadı

        lines = run_vision_ocr(temp_image)
        if lines:
            if lat is None or lon is None:
                new_lat, new_lon = parse_coordinates(lines)
                lat = lat if lat is not None else new_lat
                lon = lon if lon is not None else new_lon
            if dt_str is None:
                dt_str = parse_datetime(lines)

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
