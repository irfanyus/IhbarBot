import os
import re
import time
import subprocess
from datetime import datetime
from geocoder import reverse_geocode
from form_filler import IhbarFormFiller, ALLOWED_IMAGE_EXT, MAX_IMAGE_BYTES
from ocr_helper import extract_frame_from_video, get_video_duration
import drive_uploader
import ihlal_katalogu
from selenium import webdriver

# Türk plaka formatı: 2 hane il kodu + 1-3 harf + 2-4 rakam (örn: 09AID146, 34JJ9251)
PLATE_PATTERN = re.compile(r'^\d{2}[A-Z]{1,3}\d{2,4}$')

# Plakaları ayıran her şey ayraç sayılır. Dosya adında boşluk kullanmak
# Finder'da zahmetli olduğu için virgül de sık kullanılıyor ("74AAY507,34PH7806.mp4");
# eskiden yalnızca boşluğa bakılıyordu ve virgüllü ad tek parça sayılıp hiçbir
# plaka tanınmıyordu.
PLAKA_AYRAC = re.compile(r"[^0-9A-Za-z]+")


def plakalari_ayikla(metin):
    """Serbest metinden geçerli plakaları çıkarır (virgül/boşluk/alt çizgi/tire ayraç)."""
    if not metin:
        return []
    return [p.upper() for p in PLAKA_AYRAC.split(metin) if PLATE_PATTERN.match(p.upper())]


def parse_plates_from_filename(video_path):
    """
    Video dosya adından plaka(ları) çıkarır.
    Örn: '09AID146.mp4'            -> ['09AID146']
         '34ABC123 06XYZ789.mp4'   -> ['34ABC123', '06XYZ789']
         '74AAY507,34PH7806.mp4'   -> ['74AAY507', '34PH7806']
    Plaka formatına uymayan dosya adlarında boş liste döner.
    """
    if not video_path:
        return []
    base = os.path.splitext(os.path.basename(video_path))[0]
    return plakalari_ayikla(base)

def find_video_in_folder(folder_path):
    """
    Scans the folder for supported video files and returns the absolute path of the first match.
    """
    video_extensions = ('.mp4', '.avi', '.mkv', '.mov', '.webm', '.3gp', '.mpeg', '.mpg')
    if not os.path.exists(folder_path):
        print(f"[WARNING] Klasör bulunamadı: {folder_path}")
        return None
    
    for filename in os.listdir(folder_path):
        if filename.lower().endswith(video_extensions):
            return os.path.abspath(os.path.join(folder_path, filename))
    return None


def find_image_in_folder(folder_path):
    """
    Klasördeki ilk görseli (jpg/jpeg/png) döndürür.
    Site artık video kabul etmediği için, hazır bir ekran görüntüsü varsa
    videodan kare çıkarmaya gerek kalmadan doğrudan o kullanılır.
    """
    if not os.path.exists(folder_path):
        return None
    for filename in sorted(os.listdir(folder_path)):
        if filename.lower().endswith(ALLOWED_IMAGE_EXT):
            return os.path.abspath(os.path.join(folder_path, filename))
    return None


def prepare_image_from_video(video_path, at_seconds=5, out_dir=None):
    """
    Videodan tek bir kare çıkarıp JPEG olarak kaydeder ve yolunu döndürür.

    ihbar.ng112.gov.tr 2026 güncellemesinde video yüklemeyi kaldırdı; ek olarak
    yalnızca jpg/jpeg/png (max 5 MB) kabul ediliyor. Bu yüzden dash-cam videosu
    artık doğrudan yüklenemiyor, olayın göründüğü kare çıkarılıp o gönderiliyor.
    """
    if not video_path or not os.path.exists(video_path):
        return None
    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gorseller")
    os.makedirs(out_dir, exist_ok=True)

    # İstenen saniye videodan uzunsa ffmpeg sessizce boş çıktı üretiyor ve ihbar
    # görselsiz gidiyor; bu yüzden klibin sonuna sığacak bir kareye çekiyoruz.
    duration = get_video_duration(video_path)
    if duration and at_seconds >= duration:
        clamped = max(0, round(duration - 0.5, 1))
        print(f"[UYARI] Video {duration:.1f} sn; {at_seconds}. saniye yok. "
              f"Kare {clamped}. saniyeden alınıyor.")
        at_seconds = clamped

    base = os.path.splitext(os.path.basename(video_path))[0]
    out_path = os.path.join(out_dir, f"{base}_{at_seconds}s.jpg")
    if extract_frame_from_video(video_path, out_path, at_seconds=at_seconds):
        size = os.path.getsize(out_path)
        if size > MAX_IMAGE_BYTES:
            print(f"[UYARI] Çıkarılan kare {MAX_IMAGE_BYTES//(1024*1024)} MB sınırını aşıyor "
                  f"({size/1024/1024:.1f} MB).")
        print(f"[INFO] Videodan kare çıkarıldı ({at_seconds}. saniye): {out_path}")
        return out_path
    print("[HATA] Videodan kare çıkarılamadı (ffmpeg kurulu mu?).")
    return None

def compress_image_for_upload(image_path, out_dir=None):
    """
    Bir görseli sitenin 5 MB / 4096px sınırına sığacak şekilde JPEG'e sıkıştırır.
    Görsel zaten izin verilen tipte ve sınır altındaysa dokunmadan geri döner.
    Sitenin kendi Compressor.js'i de aynısını yapıyor (JPEG, max 4096, düşen kalite);
    bot göndermeden önce boyutu reddettiği için bu adımı burada da uyguluyoruz —
    böylece elle bırakılan büyük bir PNG/fotoğraf da 'çok büyük' diye elenmez.
    """
    from ocr_helper import _find_ffmpeg
    abs_path = os.path.abspath(image_path)
    if not os.path.exists(abs_path):
        return image_path

    ext = os.path.splitext(abs_path)[1].lower()
    if ext in ALLOWED_IMAGE_EXT and os.path.getsize(abs_path) <= MAX_IMAGE_BYTES:
        return abs_path  # zaten uygun, dokunma

    if out_dir is None:
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gorseller")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(abs_path))[0]
    out_path = os.path.join(out_dir, f"{base}_upload.jpg")

    ffmpeg = _find_ffmpeg()
    # En uzun kenarı 4096'ya indir (küçükse büyütme), sonra kaliteyi kademeli düşür.
    scale_vf = "scale='min(4096,iw)':'min(4096,ih)':force_original_aspect_ratio=decrease"
    for q in (3, 5, 8, 12, 18, 25):
        try:
            subprocess.run(
                [ffmpeg, '-y', '-i', abs_path, '-vf', scale_vf, '-q:v', str(q), out_path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
            )
        except Exception as e:
            print(f"[HATA] Görsel sıkıştırma hatası: {e}")
            return image_path
        if os.path.exists(out_path) and os.path.getsize(out_path) <= MAX_IMAGE_BYTES:
            print(f"[INFO] Görsel siteye uygun boyuta getirildi (JPEG kalite q={q}, "
                  f"{os.path.getsize(out_path)/1024:.0f} KB): {out_path}")
            return out_path

    print(f"[UYARI] Görsel en yüksek sıkıştırmada bile {MAX_IMAGE_BYTES//(1024*1024)} MB "
          f"altına inmedi; yine de en küçük hali deneniyor.")
    return out_path if os.path.exists(out_path) else image_path


def olay_detayi_sor():
    """Olay detayını katalog numarasıyla ya da serbest metinle alır.

    Numara girilirse katalogdaki etiket olduğu gibi kullanılıyor; serbest metin
    girilirse ihlal_katalogu.eslestir() maddeyi yine de bulmaya çalışıyor."""
    print("\n[INPUT] Sık ihbar edilen ihlaller:")
    etiketler = ihlal_katalogu.etiketler()
    for i, etiket in enumerate(etiketler, 1):
        print(f"  {i:2d}. {etiket}")
    girdi = input("Numara seçin veya olay detayını serbestçe yazın: ").strip()
    if girdi.isdigit() and 1 <= int(girdi) <= len(etiketler):
        secilen = etiketler[int(girdi) - 1]
        print(f"[INFO] Seçildi: {secilen}")
        return secilen
    return girdi


def madde_sec(olay_detayi):
    """Eşleşen KTK maddelerini listeleyip doğru olan(lar)ı kullanıcıya seçtirir.

    Bir ihbarda birden fazla ihlal olabildiği için virgülle çoklu seçim kabul
    ediliyor ("1,3"). Tek aday varsa sormuyor; hiç aday yoksa boş liste dönüp
    ihbarın dayanak satırı olmadan gitmesine izin veriyor - uydurma madde
    yazmaktansa hiç yazmamak doğrusu."""
    adaylar = ihlal_katalogu.adaylari_bul(olay_detayi)
    if not adaylar:
        print("[UYARI] Olay detayı katalogdaki hiçbir maddeyle eşleşmedi; "
              "ihbar kanuni dayanak satırı olmadan gönderilecek.")
        return []
    if len(adaylar) == 1:
        print(f"[INFO] Kanuni dayanak: {adaylar[0].ozet()}")
        return adaylar

    print("\n[INPUT] Olay detayına uyan maddeler (en olası ilk sırada):")
    for i, aday in enumerate(adaylar, 1):
        print(f"  {i}. {aday.ozet()}")
    print("  0. Hiçbiri - dayanak satırı eklenmesin")
    secim = input("Madde numaralarını girin, birden fazlaysa virgülle "
                  "(ör. 1,3 - ENTER = 1): ").strip()
    if secim == "0":
        print("[INFO] Kanuni dayanak eklenmeyecek.")
        return []
    if not secim:
        return [adaylar[0]]

    secilenler, hatali = [], []
    for parca in re.split(r"[^0-9]+", secim):
        if not parca:
            continue
        no = int(parca)
        if 1 <= no <= len(adaylar):
            if adaylar[no - 1] not in secilenler:
                secilenler.append(adaylar[no - 1])
        else:
            hatali.append(parca)
    if hatali:
        print(f"[UYARI] Listede olmayan numara yok sayıldı: {', '.join(hatali)}")
    if not secilenler:
        print("[UYARI] Geçerli seçim yapılmadı; ilk madde kullanılıyor.")
        return [adaylar[0]]
    print(f"[INFO] Seçilen madde(ler): {', '.join(i.madde for i in secilenler)}")
    return secilenler


def main():
    print("\n" + "="*60)
    print("                 İHBARBOT BAŞLATILIYOR")
    print("="*60)
    
    # 1. 'videolar' klasörünü tara ve videoyu tespit et
    videolar_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videolar")
    print(f"[INFO] '{videolar_folder}' dizini video dosyaları için taranıyor...")
    video_path = find_video_in_folder(videolar_folder)
    
    latitude, longitude = None, None
    datetime_str = None
    
    if video_path:
        print(f"[INFO] Video bulundu: {video_path}")
        print("[INFO] Videodan GPS koordinatları ve tarih/saat bilgileri okunmaya başlanıyor...")
        from ocr_helper import analyze_video_metadata
        gps_coords, ocr_dt = analyze_video_metadata(video_path)
        
        if gps_coords and gps_coords[0] is not None and gps_coords[1] is not None:
            latitude, longitude = gps_coords
            print(f"[OCR] Başarılı: Otomatik koordinatlar okundu -> {latitude}, {longitude}")
        else:
            print("[OCR] GPS koordinatları videodan otomatik okunamadı.")
            
        if ocr_dt:
            datetime_str = ocr_dt
            print(f"[OCR] Başarılı: Otomatik tarih/saat okundu -> {datetime_str}")
        else:
            print("[OCR] Tarih ve saat bilgisi videodan otomatik okunamadı.")
    else:
        # Video yok: dash-cam fotoğrafında da GPS bindirmesi ve tarih basılı olduğu için,
        # klasörde hazır bir görsel varsa konum/tarihi doğrudan ondan okuyabiliriz.
        hazir_gorsel = find_image_in_folder(videolar_folder)
        if hazir_gorsel:
            print(f"[INFO] Video yok; hazır görsel bulundu: {hazir_gorsel}")
            print("[INFO] Fotoğraftan GPS koordinatları ve tarih/saat okunmaya başlanıyor...")
            from ocr_helper import analyze_image_metadata
            gps_coords, ocr_dt = analyze_image_metadata(hazir_gorsel)

            if gps_coords and gps_coords[0] is not None and gps_coords[1] is not None:
                latitude, longitude = gps_coords
                print(f"[OCR] Başarılı: Otomatik koordinatlar okundu -> {latitude}, {longitude}")
            else:
                print("[OCR] GPS koordinatları fotoğraftan otomatik okunamadı.")

            if ocr_dt:
                datetime_str = ocr_dt
                print(f"[OCR] Başarılı: Otomatik tarih/saat okundu -> {datetime_str}")
            else:
                print("[OCR] Tarih ve saat bilgisi fotoğraftan otomatik okunamadı.")
        else:
            print("[WARNING] 'videolar' klasöründe video veya hazır görsel bulunamadı!")
        video_path = "VIDEO_BULUNAMADI"
        
    # 2. Eksik Bilgiler İçin Kullanıcıdan Girdi Alımı
    
    # Koordinatlar bulunamadıysa sor
    if latitude is None or longitude is None:
        print("\n[INPUT] Lütfen ihlal konumunu elinizle girin:")
        koordinat_input = input("Enlem ve Boylam (Örn: 40.9330, 29.3019): ").strip()
        try:
            lat_str, lon_str = koordinat_input.split(',')
            latitude = float(lat_str.strip())
            longitude = float(lon_str.strip())
        except ValueError:
            print("[WARNING] Geçersiz koordinat girişi! Parametre kontrolü adımında güncelleyebilirsiniz.")
            latitude, longitude = 0.0, 0.0

    # Tarih ve saat bulunamadıysa sor
    if not datetime_str:
        print("\n[INPUT] Lütfen ihlal tarih ve saatini girin:")
        datetime_str = input("Tarih ve Saat (Örn: 30.06.2026 17:21 veya boş bırakıp geçmek için ENTER): ").strip()
        if not datetime_str:
            datetime_str = datetime.now().strftime("%d.%m.%Y %H:%M")
            print(f"[INFO] Boş bırakıldı. Varsayılan zaman kullanılıyor: {datetime_str}")

    # Plaka ve Olay Detayı Sor
    print("\n[INPUT] Lütfen ihbar detaylarını girin:")
    auto_plates = parse_plates_from_filename(video_path)
    if auto_plates:
        plaka = ", ".join(auto_plates)
        print(f"[INFO] Plaka dosya adından otomatik okundu: {plaka}")
        manual = input(f"Farklı plaka için yazın (onaylamak için ENTER) [{plaka}]: ").strip().upper()
        if manual:
            plaka = manual
    else:
        plaka = input("İhbar edilecek araç plakası (Örn: 34XYZ999): ").strip().upper()
    olay_detayi = olay_detayi_sor()

    # Adres Çözümleme (İlk Adres Sorgusu)
    address_info = None
    if latitude and longitude and (latitude != 0.0 or longitude != 0.0):
        print(f"\n[INFO] Harita üzerinden adres çözümleniyor: ({latitude}, {longitude})...")
        address_info = reverse_geocode(latitude, longitude)
    else:
        address_info = {'il': 'Bilinmiyor', 'ilçe': 'Bilinmiyor', 'mahalle': 'Bilinmiyor', 'sokak': 'Bilinmiyor'}

    # 3. İnceleme ve Düzenleme Döngüsü (Review & Edit Loop)
    while True:
        print("\n" + "="*60)
        print("                 İHBAR PARAMETRELERİ KONTROLÜ")
        print("="*60)
        print(f"1. Koordinatlar : {latitude}, {longitude}")
        print(f"   Tespit Adresi: {address_info.get('il', 'Bilinmiyor')} / {address_info.get('ilçe', 'Bilinmiyor')} / {address_info.get('mahalle', 'Bilinmiyor')} / {address_info.get('sokak', 'Bilinmiyor')}")
        print(f"2. Araç Plakası : {plaka}")
        print(f"3. Olay Açıklama: {olay_detayi}")
        _adaylar = ihlal_katalogu.adaylari_bul(olay_detayi)
        if _adaylar:
            _ek = (f" (+{len(_adaylar) - 1} aday daha, birden fazlası seçilebilir)"
                   if len(_adaylar) > 1 else "")
            print(f"   Kanuni Dayanak: {_adaylar[0].ozet()}{_ek}")
        else:
            print("   Kanuni Dayanak: eşleşme yok")
        print(f"4. Tarih / Saat : {datetime_str}")
        print("="*60)
        
        choice = input("Düzenlemek istediğiniz parametrenin numarasını girin (Onaylayıp DEVAM ETMEK için ENTER'a basın): ").strip()
        
        if not choice:
            break
            
        if choice == "1":
            koordinat_input = input("Yeni Enlem ve Boylam (Örn: 40.9123, 29.2834): ").strip()
            try:
                lat_str, lon_str = koordinat_input.split(',')
                latitude = float(lat_str.strip())
                longitude = float(lon_str.strip())
                print(f"[INFO] Adres güncelleniyor: ({latitude}, {longitude})...")
                address_info = reverse_geocode(latitude, longitude)
            except ValueError:
                print("[HATA] Geçersiz giriş! Koordinat güncellenmedi.")
                
        elif choice == "2":
            plaka = input("Yeni araç plakası: ").strip().upper()
            
        elif choice == "3":
            olay_detayi = olay_detayi_sor()
            
        elif choice == "4":
            datetime_str = input("Yeni tarih/saat (Örn: 30.06.2026 17:21): ").strip()
            
        else:
            print("[HATA] Geçersiz seçim! Lütfen 1-4 arasında bir sayı girin.")

    # Açıklama metnini son haline getir
    description_text = f"Tarih/Saat: {datetime_str}\nPlaka: {plaka}\nOlay Detayı: {olay_detayi}"
    secilen_ihlaller = madde_sec(olay_detayi)
    if secilen_ihlaller:
        description_text, _ = ihlal_katalogu.dayanak_ekle(description_text, secilen_ihlaller)
        for _ihlal in secilen_ihlaller:
            print(f"[INFO] Kanuni dayanak eklendi: KTK {_ihlal.madde} - {_ihlal.resmi_tanim}")

    # Site olay açıklamasında en az 50 karakter istiyor; kısa metinde 2. adım kilitleniyor.
    while len(description_text) < 50:
        print(f"\n[UYARI] Açıklama {len(description_text)} karakter; site en az 50 karakter istiyor.")
        olay_detayi = input("Olay detayını biraz daha ayrıntılı yazın: ").strip()
        description_text = f"Tarih/Saat: {datetime_str}\nPlaka: {plaka}\nOlay Detayı: {olay_detayi}"
        if secilen_ihlaller:
            description_text, _ = ihlal_katalogu.dayanak_ekle(description_text, secilen_ihlaller)

    # 4. Yüklenecek görselin hazırlanması
    # Site (v1.1.38) video yüklemeyi kaldırdı: yalnızca jpg/jpeg/png kabul ediliyor.
    image_path = find_image_in_folder(videolar_folder)
    if image_path:
        print(f"\n[INFO] Yüklenecek görsel bulundu: {image_path}")
    elif video_path and video_path != "VIDEO_BULUNAMADI":
        print("\n[INFO] Site artık video kabul etmiyor; videodan bir kare çıkarılacak.")
        saniye = 5
        while True:
            girdi = input(f"Kare hangi saniyeden alınsın? [{saniye}] (görselsiz devam için 'yok'): ").strip()
            if girdi.lower() in ("yok", "hayır", "hayir"):
                image_path = None
                break
            if girdi:
                try:
                    saniye = int(girdi)
                except ValueError:
                    print("[HATA] Saniye bir sayı olmalı.")
                    continue
            image_path = prepare_image_from_video(video_path, at_seconds=saniye)
            if not image_path:
                break
            onay = input("Bu kare kullanılsın mı? (ENTER = evet, başka saniye için sayı yazın): ").strip()
            if not onay:
                break
            try:
                saniye = int(onay)
            except ValueError:
                break
    else:
        image_path = None

    # Görsel siteye uygun mu? Büyük bir PNG/fotoğraf ya da 5 MB'ı aşan bir kare ise
    # site reddediyor; göndermeden önce JPEG'e sıkıştırıp sınırın altına indiriyoruz.
    if image_path:
        image_path = compress_image_for_upload(image_path)

    # 4b. Videoyu Drive'a yükleyip linkini açıklamaya ekle
    # Site videoyu forma kabul etmiyor (eklense bile sessizce düşüyor), bu yüzden
    # kaydın kendisi ancak bu linkle iletilebiliyor.
    if video_path and video_path != "VIDEO_BULUNAMADI" and os.path.exists(video_path):
        if not drive_uploader.is_configured():
            print(f"\n[UYARI] {drive_uploader.setup_hint()}")
            print("[UYARI] İhbar, video linki olmadan sürdürülecek.")
        elif input("\nVideo Drive'a yüklenip linki ihbara eklensin mi? (E/h): ").strip().lower() not in ("h", "hayir", "hayır", "n"):
            try:
                link = drive_uploader.upload_and_get_link(video_path)
                description_text = drive_uploader.append_link_to_description(description_text, link)
            except drive_uploader.DriveUploadError as e:
                print(f"[UYARI] Video Drive'a yüklenemedi: {e}")
                print("[UYARI] İhbar, video linki olmadan sürdürülüyor.")

    # 5. Selenium Form Doldurma Adımı
    print("\n[INFO] Tarayıcı başlatılıyor...")
    
    driver = None
    try:
        options = webdriver.ChromeOptions()
        options.add_experimental_option("detach", True)
        
        driver = webdriver.Chrome(options=options)
        filler = IhbarFormFiller(driver)
        
        if not image_path:
            print("[WARNING] Yüklenecek görsel olmadığı için form görselsiz doldurulacaktır.")
        else:
            print(f"[INFO] Yükleme için seçilen görsel: {image_path}")

        # Formu doldur
        gonderildi = filler.fill_form(address_info, image_path or "GORSEL_BULUNAMADI",
                                      description_text)
        if not gonderildi:
            print("\n[SONUÇ] İhbar GÖNDERİLMEDİ. Yukarıdaki hatayı giderip yeniden dene.")
        
        print("\n[INFO] İşlem tamamlandı. Tarayıcı kontrolünüz için açık bırakılıyor.")
        
    except Exception as e:
        print(f"\n[WARNING/ERROR] Selenium çalışırken hata oluştu: {e}")
        print("Lütfen Chrome sürümünüz ile ChromeDriver sürümünüzün uyumlu olduğundan emin olun.")
    finally:
        # Chrome kullanıcıda kalsın diye driver.quit() çağrılmıyor: detach=True
        # olsa bile quit() Chrome'u da kapatıyor. service.stop() yalnızca
        # chromedriver'ı sonlandırıyor; bu olmadan her çalıştırmadan geriye
        # öksüz bir chromedriver süreci kalıyordu.
        if driver is not None:
            try:
                driver.service.stop()
                print("[INFO] chromedriver kapatıldı; Chrome penceresi sizde kalıyor.")
            except Exception as e:
                print(f"[UYARI] chromedriver kapatılamadı: {e}")

if __name__ == "__main__":
    main()
