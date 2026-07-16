import os
import re
import time
from datetime import datetime
from geocoder import reverse_geocode
from form_filler import IhbarFormFiller
from selenium import webdriver

# Türk plaka formatı: 2 hane il kodu + 1-3 harf + 2-4 rakam (örn: 09AID146, 34JJ9251)
PLATE_PATTERN = re.compile(r'^\d{2}[A-Z]{1,3}\d{2,4}$')

def parse_plates_from_filename(video_path):
    """
    Video dosya adından plaka(ları) çıkarır.
    Örn: '09AID146.mp4' -> ['09AID146']
         '34ABC123 06XYZ789.mp4' -> ['34ABC123', '06XYZ789']  (birden çok plaka boşlukla ayrılır)
    Plaka formatına uymayan dosya adlarında boş liste döner.
    """
    if not video_path:
        return []
    base = os.path.splitext(os.path.basename(video_path))[0]
    plates = [t.upper() for t in base.split() if PLATE_PATTERN.match(t.upper())]
    return plates

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
        print("[WARNING] 'videolar' klasöründe herhangi bir video bulunamadı!")
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
    olay_detayi = input("Olay detayı açıklaması: ").strip()

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
            olay_detayi = input("Yeni olay detayı açıklaması: ").strip()
            
        elif choice == "4":
            datetime_str = input("Yeni tarih/saat (Örn: 30.06.2026 17:21): ").strip()
            
        else:
            print("[HATA] Geçersiz seçim! Lütfen 1-4 arasında bir sayı girin.")

    # Açıklama metnini son haline getir
    description_text = f"Tarih/Saat: {datetime_str}\nPlaka: {plaka}\nOlay Detayı: {olay_detayi}"
    
    # 4. Selenium Form Doldurma Adımı
    print("\n[INFO] Tarayıcı başlatılıyor...")
    
    try:
        options = webdriver.ChromeOptions()
        options.add_experimental_option("detach", True)
        
        driver = webdriver.Chrome(options=options)
        filler = IhbarFormFiller(driver)
        
        if not video_path or video_path == "VIDEO_BULUNAMADI":
            print(f"[WARNING] Yüklenecek video dosyası bulunamadığı için form video yüklenmeden doldurulacaktır.")
        else:
            print(f"[INFO] Yükleme için seçilen video: {video_path}")
            
        # Formu doldur
        filler.fill_form(address_info, video_path, description_text)
        
        print("\n[INFO] İşlem tamamlandı. Tarayıcı kontrolünüz için açık bırakılıyor.")
        
    except Exception as e:
        print(f"\n[WARNING/ERROR] Selenium çalışırken hata oluştu: {e}")
        print("Lütfen Chrome sürümünüz ile ChromeDriver sürümünüzün uyumlu olduğundan emin olun.")

if __name__ == "__main__":
    main()
