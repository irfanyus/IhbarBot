import time
import os
import re
import json
import sys
from urllib.parse import unquote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (TimeoutException, InvalidSessionIdException,
                                        NoSuchWindowException, WebDriverException)
from selenium.webdriver.common.keys import Keys

# ==========================================
# 1. TURKISH UPPERCASE HELPER
# ==========================================
def turkish_upper(text: str) -> str:
    if not text:
        return ""
    mapping = {"i": "İ", "ı": "I", "ğ": "Ğ", "ü": "Ü", "ş": "Ş", "ö": "Ö", "ç": "Ç"}
    return "".join(mapping.get(c, c.upper()) for c in text)


def turkish_lower(text: str) -> str:
    """turkish_upper'ın tersi. Site metni tr kurallarıyla büyütüp küçülttüğü için,
    yazdığımızla okuduğumuzu karşılaştırırken aynı kuralı kullanmak gerekiyor."""
    if not text:
        return ""
    mapping = {"İ": "i", "I": "ı", "Ğ": "ğ", "Ü": "ü", "Ş": "ş", "Ö": "ö", "Ç": "ç"}
    return "".join(mapping.get(c, c.lower()) for c in text)


# Selenium hataları ekrana koca bir chromedriver yığını basıyor; log'da işe
# yarayan tek satır ilki. Kullanıcı panelde bunu okuyor, yığın onu boğuyor.
def kisa_hata(e) -> str:
    metin = str(e).strip()
    return metin.splitlines()[0] if metin else e.__class__.__name__


# Kullanıcı tarayıcı penceresini kapattığında (ya da Chrome çöktüğünde) sonraki
# her Selenium çağrısı bu hatalarla düşüyor. Otomasyonun devam etmesi anlamsız:
# form gitmedi, gitmiş gibi davranmamalı.
TARAYICI_YOK = (InvalidSessionIdException, NoSuchWindowException)


def tarayici_kapandi_mi(e) -> bool:
    """Hata 'tarayıcı gitti' anlamına mı geliyor?

    İki ayrı biçimde gelebiliyor: kullanıcı yalnızca pencereyi kapatırsa
    chromedriver ayakta kalır ve Selenium 'invalid session id' der; chromedriver
    da ölürse (ya da driver.quit() çağrıldıysa) hata urllib3'ten 'connection
    refused' olarak gelir ve WebDriverException bile değildir.
    """
    if isinstance(e, TARAYICI_YOK):
        return True
    metin = str(e).lower()
    return any(im in metin for im in (
        "invalid session id", "no such window", "not connected to devtools",
        "target window already closed", "browser has closed the connection",
        "max retries exceeded", "connection refused",
        "failed to establish a new connection"))


# ==========================================
# 2. USER PROFILE CONFIGURATION
# ==========================================
# Kişisel bilgiler config.json'dan okunur (repoya dahil edilmez).
# İlk kurulumda config.example.json dosyasını config.json olarak
# kopyalayıp kendi bilgilerinizle doldurun.
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def _load_user_config() -> dict:
    if not os.path.exists(_CONFIG_PATH):
        print("[HATA] config.json bulunamadı!")
        print("       config.example.json dosyasını config.json olarak kopyalayıp")
        print("       kendi kişisel bilgilerinizle doldurun.")
        sys.exit(1)
    with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

USER_CONFIG = _load_user_config()


# ==========================================
# 2b. SITE MAP (v1.1.38 — 3 adımlı form)
# ==========================================
# Site 2026 yazında yenilendi: tek sayfalık form üç ayrı sayfaya bölündü.
# Her adım kendi URL'sinde ve aralarında "Devam Et" (type=submit) ile geçiliyor.
SITE_BASE  = "https://ihbar.ng112.gov.tr"
STEP_URLS  = {
    "konum":   f"{SITE_BASE}/ihbar-olustur/olay-vaka-konumu",
    "detay":   f"{SITE_BASE}/ihbar-olustur/olay-vaka-detayi",
    "kisisel": f"{SITE_BASE}/ihbar-olustur/kisisel-bilgiler",
}

# Güvenlik birimi radio'ları görünmez (opacity-0); ayırt edici tek şey value.
GUVENLIK_BIRIMI_VALUES = {
    "EMNİYET":        "1",
    "JANDARMA":       "4",
    "SAHİL GÜVENLİK": "7",   # site tarafında çoğu ilde disabled
}

# Açıklama alanı artık EN AZ 50 karakter istiyor (yup: description.min(50)).
DESCRIPTION_MIN_LEN = 50

# Görsel yüklenince site dosyayı /api/scan-file'a atıp taramayı bekliyor ve
# tarama bitene kadar 'Devam Et' kilitli kalıyor. Servis yanıt vermezse form
# tamamen kilitleniyor (kartta silme ikonu bile çıkmıyor), bu yüzden sınırlı
# süre bekleyip görselsiz yeniden deniyoruz.
SCAN_TIMEOUT_SEC = 60

# Yüklenecek dosya artık VİDEO DEĞİL: site yalnızca jpg/jpeg/png kabul ediyor.
# Sınır 15 MB değil 5 MB (bundle'daki doğrulama: `if (file.size > 5242880) throw FILE_SIZE_ERROR`).
# Site ayrıca 1 MB üstü görselleri tarayıcıda Compressor.js ile yeniden JPEG'e sıkıştırıyor.
ALLOWED_IMAGE_EXT = (".jpg", ".jpeg", ".png")
MAX_IMAGE_BYTES   = 5 * 1024 * 1024

# Site uzantıya değil dosyanın ilk baytlarına bakıyor; imza tutmazsa FILE_TYPE_MISMATCH
# atıp dosyayı sessizce eliyor (uzantısı .jpg olan bir video da buradan geri döner).
IMAGE_MAGIC_BYTES = {
    ".jpg":  (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png":  (b"\x89PNG\r\n\x1a\n",),
}

# Sitenin alan bazlı karakter kısıtları (JS bundle'daki regex'lerden çıkarıldı).
# Açıklama:  EXCEPT_SEMICOLON
DESCRIPTION_ALLOWED_RE = re.compile(r"[0-9A-ZÇĞİÖŞÜa-zçğıöşü\s!@#$%&()_+\-=:\"',.?/…]")
# İkamet adresi: ONLY_LETTERS_SOME_CHARACTERS_AND_NUMBERS (min 10, max 200)
ADDRESS_ALLOWED_RE     = re.compile(r"[0-9A-ZÇĞİÖŞÜa-zçğıöşü\s./-]")


def sanitize_for_site(text: str, allowed_re: re.Pattern) -> str:
    """Sitenin kabul etmediği karakterleri boşluğa çevirip fazla boşlukları sadeleştirir.
    Yasaklı bir karakter kalırsa React formu 'geçersiz alan' diyerek Devam Et'i kilitliyor."""
    if not text:
        return ""
    cleaned = "".join(c if allowed_re.match(c) else " " for c in text)
    return " ".join(cleaned.split())


# ==========================================
# 2c. ADDRESS SUFFIX HANDLING
# ==========================================
# Sitedeki kısaltmalar tahmin edilemiyor (CADDESİ -> 'CD.' gelebiliyor, 'CAD.' değil).
# Bu yüzden aramada ek hiç yazılmaz; taban isim yazılır, seçeneklerden ek TÜRÜ
# uyumlu olan seçilir (örn. 'MİLLET CD.' vs 'MİLLET SK.' ayrımı).
ADDRESS_SUFFIXES = [
    ("MAH", ["MAHALLESİ", "MAHALLE", "MAH.", "MAH"]),
    ("SK",  ["SOKAĞI", "SOKAK", "SOK.", "SOK", "SK.", "SK"]),
    ("CD",  ["CADDESİ", "CADDE", "CAD.", "CAD", "CD.", "CD"]),
    ("BLV", ["BULVARI", "BULVAR", "BULV.", "BLV.", "BLV", "BUL.", "BUL"]),
]

def split_address_suffix(text: str):
    """
    'MİLLET CADDESİ' -> ('MİLLET', 'CD');  'ORKİDE SK.' -> ('ORKİDE', 'SK')
    Ek yoksa: ('İSTANBUL', None)
    """
    t = text.strip()
    for family, variants in ADDRESS_SUFFIXES:
        for v in variants:
            if t.endswith(" " + v):
                return t[: -len(v)].strip(), family
    return t, None


def normalize_separators(text: str) -> str:
    """Tire/eğik çizgi gibi ayraçları boşluğa çevirip fazla boşlukları sadeleştirir.
    Geocoder 'KURTKÖY-PENDİK BAĞLANTISI' derken site 'KURTKÖY PENDİK ...' gösteriyor;
    tire yüzünden arama ve seçenek eşleşmesi kaçmasın diye normalize ediyoruz."""
    if not text:
        return ""
    return " ".join(text.replace("-", " ").replace("/", " ").split())


# ==========================================
# 3. SELECTORS
# ==========================================
SELECTORS = {
    # Her adımın kendi "Devam Et" butonu; formun butonu type=submit,
    # tanıtım modalındaki buton type=button olduğu için ikisi karışmıyor.
    "devam_et":        (By.XPATH, "//button[@type='submit'][contains(normalize-space(.),'Devam Et')]"),
    # Açılışta çıkan "HAYAT 112 Mobil Uygulaması" tanıtım modalı formu bloke ediyor.
    "promo_modal":     (By.CSS_SELECTOR, ".ant-modal"),
    "promo_modal_btn": (By.XPATH, "//div[contains(@class,'ant-modal')]//button[@type='button'][contains(normalize-space(.),'Devam Et')]"),
    "file_input":      (By.ID, "file"),
    "captcha":         (By.ID, "h-captcha"),
    "otp_inputs":      (By.CSS_SELECTOR, ".ant-otp input"),
}


class IhbarFormFiller:
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(self.driver, 20)

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────

    def fill_form(self, address_info: dict, image_path: str, description_text: str,
                  wait_callback=None, guvenlik_birimi: str = "Emniyet",
                  gorsel_yukle: bool = True) -> bool:
        """
        Yeni (v1.1.38) üç adımlı formu doldurur:
          ADIM 1  /ihbar-olustur/olay-vaka-konumu    → il/ilçe/mahalle/sokak + güvenlik birimi
          ADIM 2  /ihbar-olustur/olay-vaka-detayi    → olay açıklaması + görsel (jpg/png)
          ADIM 3  /ihbar-olustur/kisisel-bilgiler    → kişisel bilgiler + KVKK + hCaptcha + SMS

        `image_path` artık VİDEO DEĞİL, bir görseldir (jpg/jpeg/png, max 5 MB).
        Site video yüklemeyi tamamen kaldırdı; videodan kare çıkarma işi çağıran
        tarafta (app.py / main.py) yapılıyor.

        Görsel yüklenip site taraması takılırsa (bkz. SCAN_TIMEOUT_SEC) form geri
        alınamaz şekilde kilitlendiği için, aynı ihbar görselsiz olarak baştan doldurulur.

        Dönüş: ihbar gerçekten gönderildiyse (son 'Devam Et'e basılıp SMS aşamasına
        geçildiyse) True. Çağıran taraf ihbarı geçmişe YALNIZCA bu durumda yazmalı.
        """
        try:
            return self._fill_form(address_info, image_path, description_text,
                                   wait_callback, guvenlik_birimi, gorsel_yukle)
        except Exception as e:
            if not tarayici_kapandi_mi(e):
                raise
            # Tarayıcı ortadan kalktığında Selenium'un her çağrısı patlıyor;
            # kullanıcıya sayfalarca yığın yerine tek cümle göstermek yeterli.
            print("\n[HATA] Tarayıcı penceresi kapanmış — ihbar GÖNDERİLMEDİ.")
            print("       İhbar geçmişine eklenmedi; aracı yeniden ihbar edebilirsin.")
            return False

    def _fill_form(self, address_info, image_path, description_text,
                   wait_callback, guvenlik_birimi, gorsel_yukle) -> bool:
        istenen_gorsel = image_path if gorsel_yukle else None
        ok = self._fill_steps(address_info, istenen_gorsel, description_text, guvenlik_birimi)

        if not ok and istenen_gorsel:
            print("\n[INFO] Görselli deneme başarısız oldu — form görselsiz olarak baştan dolduruluyor.")
            print("[INFO] (Görseli daha sonra elle eklemek isterseniz sitenin tarama servisi düzelmiş olmalı.)")
            ok = self._fill_steps(address_info, None, description_text, guvenlik_birimi)

        if not ok:
            print("[HATA] Form doldurulamadı. Tarayıcıdan elle devam edebilirsiniz.")
            return False

        # ── hCaptcha (elle) ───────────────────────────────────────────
        print("\n[WAIT] Form doldurma tamamlandı.")
        print("[WAIT] Lütfen tarayıcıda hCaptcha doğrulamasını elle yapın.")
        if wait_callback:
            wait_callback("hcaptcha", "Robot doğrulamasını tamamlayıp 'Devam Et' butonuna tıklayın.")
        else:
            input("hCaptcha'yı tamamlayıp ENTER'a basın...")

        # ── Gönder (son adımın 'Devam Et'i SMS doğrulamasını başlatır) ─
        print("[INFO] Son adımın 'Devam Et' butonuna tıklanıyor (SMS gönderilecek)...")
        if not self._click_element(SELECTORS["devam_et"], "Devam Et (Gönder)"):
            # Buraya kadar gelip son tıklama tutmadıysa ihbar GÖNDERİLMEMİŞ
            # OLABİLİR - ama kesin değil. En sık sebep: kullanıcı hCaptcha'yı
            # yaparken sitenin kendi 'Devam Et'ine de basmış oluyor, sayfa SMS
            # adımına geçiyor ve buton artık DOM'da olmadığı için tıklama
            # başarısız sayılıyordu. 10.09.2026'daki düzeltme bu durumu da
            # "gönderilmedi" kabul ediyordu; gerçekte gönderilmiş ihbar geçmişe
            # yazılmıyor, aynı araç tekrar ihbar edilebilir görünüyordu.
            if self._sms_asamasinda_mi():
                print("[INFO] Sayfa zaten SMS adımında — ihbar elle gönderilmiş görünüyor.")
            elif wait_callback:
                # Kesin karar veremiyoruz. Tarayıcı açık olduğuna göre tek
                # güvenilir kaynak kullanıcı: 'Devam Et' = gönderdim.
                print("[UYARI] Son 'Devam Et'e basılamadı ve sayfa SMS adımında görünmüyor.")
                print("        İhbarı tarayıcıdan elle gönderdiyseniz 'Devam Et'e basın; "
                      "göndermediyseniz 'TÜMÜNÜ TEMİZLE' ile iptal edin.")
                wait_callback("gonderim_onayi",
                              "İhbarı elle gönderdiyseniz 'Devam Et'e basın "
                              "(göndermediyseniz TÜMÜNÜ TEMİZLE).")
                print("[INFO] Gönderim kullanıcı tarafından onaylandı.")
            else:
                print("[HATA] İhbar GÖNDERİLMEDİ — son adımın 'Devam Et'ine basılamadı.")
                print("       SMS gelmeyecek; ihbar geçmişine de eklenmeyecek.")
                print("       Tarayıcı hâlâ açıksa formu elden gönderebilirsin, "
                      "kapandıysa ihbarı baştan başlatman gerekiyor.")
                return False

        # ── SMS Doğrulama ─────────────────────────────────────────────
        print("\n[WAIT] SMS doğrulama kodu bekleniyor...")
        if wait_callback:
            sms_code = wait_callback("sms", "SMS kodunu girin (boş bırakabilirsiniz):")
        else:
            sms_code = input("SMS kodu (boş=geç): ").strip()

        if sms_code:
            self._fill_otp(sms_code)
        return True

    def _fill_steps(self, address_info, image_path, description_text, guvenlik_birimi) -> bool:
        """Üç adımı baştan doldurur. Bir adımda takılırsa False döner (yeniden denenebilir)."""
        print(f"[INFO] Navigating to {STEP_URLS['konum']}...")
        self.driver.get(STEP_URLS["konum"])
        time.sleep(3)
        self._dismiss_promo_modal()

        print("\n[ADIM 1/3] Olay/Vaka Konumu")
        self._fill_location_step(address_info, guvenlik_birimi)
        if not self._click_devam_et("olay-vaka-detayi"):
            print("[HATA] 1. adımdan geçilemedi. Eksik/geçersiz alan olabilir; tarayıcıdan kontrol edin.")
            return False

        print("\n[ADIM 2/3] Olay/Vaka Detayı")
        if not self._fill_detail_step(description_text, image_path):
            return False
        # Açıklamada link varsa site linki tarayana kadar butonu açmıyor.
        if not self._click_devam_et("kisisel-bilgiler", enable_timeout=90):
            print("[HATA] 2. adımdan geçilemedi. Açıklama veya görsel reddedilmiş olabilir.")
            return False

        print("\n[ADIM 3/3] Kişisel Bilgileriniz")
        self._fill_personal_step()
        return True

    # ──────────────────────────────────────────────────────────────────────
    # ADIM 1 — KONUM
    # ──────────────────────────────────────────────────────────────────────

    def _fill_location_step(self, address_info: dict, guvenlik_birimi: str):
        print("[INFO] Selecting location address details...")

        if address_info.get("il") not in (None, "Bilinmiyor"):
            self._select_ant_dropdown("cityDropdown", address_info["il"])
            self._wait_for_enabled("districtDropdown", timeout=8)

        # Mahalle ile sokak birbirine bağlı: site sokak listesini seçilen mahalleye
        # göre süzüyor. Koordinat iki mahallenin sınırına düşerse (sokak sınır
        # boyunca uzanıyorsa) geocoder hangisinin resmî kayıt olduğunu bilemiyor —
        # bunu yalnızca sitenin listesi biliyor. Bu yüzden adayları sırayla deneyip
        # sokağın gerçekten bulunduğu mahallede kalıyoruz. (10.09.2026: Tariki Has
        # Sk. Nominatim'e göre Kozyatağı'nda, resmî kayıtta Bostancı'da.)
        #
        # Aynı sorun ilçe düzeyinde de var: bir bulvar iki ilçenin sınırında
        # uzanabiliyor ve nokta yanlış tarafa düşüyor (22.09.2026: Eşref Bitlis
        # Bulvarı Sultanbeyli görünüyor, kayıt Pendik/Yenişehir'de). Bu yüzden
        # döngü iki katmanlı: ilçe adayı x mahalle adayı.
        ilce_adaylari = [i for i in (address_info.get("ilce_adaylari")
                                     or [address_info.get("ilçe")])
                         if i and i != "Bilinmiyor"]
        mahalle_adaylari = [m for m in (address_info.get("mahalle_adaylari")
                                        or [address_info.get("mahalle")])
                            if m and m != "Bilinmiyor"]
        sokak = address_info.get("sokak")
        sokak_gerekli = sokak not in (None, "Bilinmiyor")

        if not self._konum_adaylarini_dene(ilce_adaylari, mahalle_adaylari,
                                           sokak, sokak_gerekli):
            print(f"[UYARI] Konum denenen kombinasyonların hiçbirinde tamamlanamadı "
                  f"(ilçe: {', '.join(ilce_adaylari) or '-'} | "
                  f"mahalle: {', '.join(mahalle_adaylari) or '-'}). "
                  f"İlçe/mahalle/sokak alanlarını elle seçmen gerekiyor.")

        # Close any open dropdown popup (mousedown, NOT ESC — ESC deselects in Ant Design)
        self._close_open_dropdowns()
        time.sleep(1)

        print(f"[INFO] Güvenlik birimi seçiliyor: {guvenlik_birimi}")
        self._select_guvenlik_birimi(guvenlik_birimi)

    def _konum_adaylarini_dene(self, ilce_adaylari, mahalle_adaylari,
                               sokak, sokak_gerekli) -> bool:
        """İlçe x mahalle kombinasyonlarını sırayla deneyip sokağı bulmaya çalışır.

        İlçe değişince site mahalle ve sokak listelerini sıfırlıyor, bu yüzden
        her ilçe için mahalle döngüsü baştan dönüyor. Bir mahalle yalnızca tek
        bir ilçeye ait olduğundan yanlış eşleşmeler listede bulunamayıp
        kendiliğinden eleniyor."""
        ilk_kombinasyon = True
        for ilce in ilce_adaylari:
            if not self._select_ant_dropdown("districtDropdown", ilce):
                print(f"[INFO] İlçe listesinde bulunamadı: {ilce}")
                continue
            self._wait_for_enabled("neighboorhoodDropdown", timeout=8)

            for mahalle in mahalle_adaylari:
                if not self._select_ant_dropdown("neighboorhoodDropdown", mahalle):
                    continue
                self._wait_for_enabled("streetDropdown", timeout=8)

                if not sokak_gerekli:
                    return True
                if self._select_ant_dropdown("streetDropdown", sokak):
                    if not ilk_kombinasyon:
                        print(f"[INFO] Konum sınır komşusunda bulundu: {ilce} / {mahalle}")
                    return True

                print(f"[INFO] '{sokak}' {ilce} / {mahalle} listesinde yok; "
                      f"sonraki aday deneniyor.")
                self._close_open_dropdowns()
                ilk_kombinasyon = False
            ilk_kombinasyon = False

        # Hiçbiri tutmadı: kullanıcının elle düzeltebilmesi için formu ilk
        # adayla dolu bırak, boş bırakma.
        if ilce_adaylari:
            self._select_ant_dropdown("districtDropdown", ilce_adaylari[0])
            self._wait_for_enabled("neighboorhoodDropdown", timeout=8)
            if mahalle_adaylari:
                self._select_ant_dropdown("neighboorhoodDropdown", mahalle_adaylari[0])
        return False

    def _select_guvenlik_birimi(self, birim: str):
        """
        Güvenlik birimi artık ant-radio-wrapper değil: her seçenek bir <label> kartı ve
        içindeki <input type=radio> tamamen görünmez (opacity-0). Tek ayırt edici alan
        value: Emniyet=1, Jandarma=4, Sahil Güvenlik=7. Görünmez olduğu için JS click şart.
        """
        value = GUVENLIK_BIRIMI_VALUES.get(turkish_upper(birim.strip()))
        if value is None:
            print(f"[UYARI] Bilinmeyen güvenlik birimi '{birim}' — Emniyet seçiliyor.")
            value = GUVENLIK_BIRIMI_VALUES["EMNİYET"]
        try:
            radios = self.driver.find_elements(By.CSS_SELECTOR, f"input[type='radio'][value='{value}']")
            if not radios:
                print(f"[WARNING] Güvenlik birimi radio bulunamadı (value={value}).")
                return
            radio = radios[0]
            if radio.get_attribute("disabled") is not None:
                print(f"[UYARI] '{birim}' bu konumda seçilemiyor (disabled) — atlanıyor.")
                return
            self._js_click(radio)
            time.sleep(0.5)
            if radio.is_selected():
                print(f"[INFO] Güvenlik birimi seçildi: {birim}")
            else:
                # Yedek: görünür kart (label) üzerinden tıkla
                label = radio.find_element(By.XPATH, "./ancestor::label[1]")
                self._js_click(label)
                time.sleep(0.5)
                print(f"[INFO] Güvenlik birimi label üzerinden seçildi: {birim}")
        except Exception as e:
            print(f"[ERROR] Güvenlik birimi seçilemedi: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # ADIM 2 — DETAY
    # ──────────────────────────────────────────────────────────────────────

    def _fill_detail_step(self, description_text: str, image_path: str) -> bool:
        print("[INFO] Writing incident description...")
        safe_desc = sanitize_for_site(description_text.replace("\n", " - "), DESCRIPTION_ALLOWED_RE)[:3000]
        if len(safe_desc) < DESCRIPTION_MIN_LEN:
            print(f"[UYARI] Açıklama {len(safe_desc)} karakter; site en az {DESCRIPTION_MIN_LEN} karakter istiyor. "
                  f"Olay detayını uzatmadan bu adım geçilemez.")
        self._fill_text_field("description", safe_desc, "vaka_description", is_textarea=True)
        time.sleep(1)
        self._verify_description_links(safe_desc)

        if image_path and image_path not in ("VIDEO_BULUNAMADI", "GORSEL_BULUNAMADI"):
            return self._upload_image(image_path)

        print("[INFO] Görsel eklenmeden devam ediliyor.")
        return True

    # Açıklamaya yazılan Drive linki sitede iki dönüşümden geçiyor (bkz. CLAUDE.md
    # "Açıklamadaki linkler"): alan yazılanı anında tr-büyük harfe çeviriyor,
    # alandan çıkılınca da sunucu metni tarayıp bulduğu adresi küçük harfli
    # haliyle geri yazıyor. drive_uploader.armor_link_for_site() linki bu tura
    # dayanacak biçimde kodluyor; burada turun gerçekten temiz bittiğini
    # doğruluyoruz. Doğrulamazsak bozuk link fark edilmeden ihbara gidiyor —
    # 10.09.2026'da tam olarak bu oldu.
    _LINK_PREFIX = "https://drive.google.com/file/d/"

    def _drive_ids(self, text: str):
        """Metindeki Drive linklerinin çözülmüş dosya kimlikleri.
        Adresin gövdesi tr-küçük harfle aranıyor (site 'DRİVE.GOOGLE.COM' yazmış
        olabilir) ama kimlik HAM haliyle çözülüyor — büyük/küçük harf farkını
        yutarsak zaten aradığımız bozulmayı göremeyiz."""
        ids = []
        for token in text.split():
            low = turkish_lower(token)
            if low.startswith(self._LINK_PREFIX):
                ids.append(unquote(token[len(self._LINK_PREFIX):].split("/")[0]))
        return ids

    def _verify_description_links(self, written_text: str, timeout: int = 30) -> bool:
        expected = self._drive_ids(written_text)
        if not expected:
            return True

        els = self.driver.find_elements(By.ID, "description")
        if not els:
            print("[UYARI] Açıklama alanı okunamadı; video linki doğrulanamadı.")
            return False
        element = els[0]

        # Alandan çıkmak sitenin bağlantı taramasını tetikliyor; tarama bitmeden
        # alanın içeriği düzelmiş olmuyor.
        self.driver.execute_script("arguments[0].focus(); arguments[0].blur();", element)

        deadline = time.time() + timeout
        while time.time() < deadline:
            current = element.get_attribute("value") or ""
            if all(fid in self._drive_ids(current) for fid in expected):
                print("[INFO] Video linki açıklamada bozulmadan duruyor.")
                return True
            time.sleep(1)

        print("[UYARI] Site açıklamadaki video linkini bozdu — ihbar açılmayan bir linkle gidecek.")
        for fid in expected:
            print(f"        Doğru link: {self._LINK_PREFIX}{fid}/view")
        print("        Linki memura ayrıca (telefon/WhatsApp) iletmen gerekecek.")
        return False

    def _upload_image(self, image_path: str):
        """
        Görseli gizli <input type='file' id='file'> üzerinden yükler.
        Site yalnızca jpg/jpeg/png ve 5 MB altını kabul ediyor; yükleme sonrası
        dosyayı virüs taramasına gönderip sonucu 5 sn'de bir yokluyor (SCAN_FILE →
        GET_ANALYSE_SCAN_REPORT). Tarama bitene kadar 'Devam Et' pasif kalıyor,
        bu yüzden yüklemeden sonra butonun aktifleşmesini bekliyoruz.
        """
        abs_path = os.path.abspath(image_path)
        ext = os.path.splitext(abs_path)[1].lower()

        if not os.path.exists(abs_path):
            print(f"[HATA] Görsel bulunamadı: {abs_path}")
            return False
        if ext not in ALLOWED_IMAGE_EXT:
            print(f"[HATA] Site bu dosya tipini kabul etmiyor: '{ext}'. "
                  f"İzin verilenler: {', '.join(ALLOWED_IMAGE_EXT)} (video yüklenemiyor).")
            return False

        # Uzantı doğru olsa da içerik JPEG/PNG değilse site dosyayı sessizce eliyor:
        # yükleme kartı görünür ama tarama hiç başlamaz, ihbara da bir şey eklenmez.
        with open(abs_path, "rb") as fh:
            header = fh.read(8)
        if not any(header.startswith(sig) for sig in IMAGE_MAGIC_BYTES[ext]):
            print(f"[HATA] Dosyanın uzantısı '{ext}' ama içeriği gerçek bir JPEG/PNG değil. "
                  f"Site imza kontrolünde (FILE_TYPE_MISMATCH) bunu reddediyor.")
            return False

        size = os.path.getsize(abs_path)
        if size > MAX_IMAGE_BYTES:
            print(f"[HATA] Görsel çok büyük ({size / 1024 / 1024:.1f} MB). "
                  f"Sınır {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
            return False

        print(f"[INFO] Görsel yükleniyor: {abs_path} ({size / 1024:.0f} KB)")
        try:
            file_inputs = self.driver.find_elements(*SELECTORS["file_input"])
            if not file_inputs:
                time.sleep(2)
                file_inputs = self.driver.find_elements(*SELECTORS["file_input"])
            if not file_inputs:
                print("[WARNING] Dosya input'u DOM'da bulunamadı! Lütfen manuel yükleyin.")
                return False

            file_input = file_inputs[0]
            # display:none olduğu için Selenium doğrudan dokunamaz; görünür yapıyoruz.
            self.driver.execute_script("""
                arguments[0].style.display  = 'block';
                arguments[0].style.opacity  = '1';
                arguments[0].style.position = 'fixed';
                arguments[0].style.top      = '0';
                arguments[0].style.left     = '0';
                arguments[0].style.zIndex   = '999999';
            """, file_input)
            time.sleep(0.3)
            file_input.send_keys(abs_path)
            print("[INFO] Görsel forma verildi, site taramasının bitmesi bekleniyor...")
            return self._wait_for_file_scan()
        except Exception as e:
            print(f"[ERROR] Görsel yükleme hatası: {e}. Lütfen manuel yükleyin.")
            return False

    def _wait_for_file_scan(self, timeout: int = SCAN_TIMEOUT_SEC):
        """Yüklenen görselin taraması bitip 'Devam Et' tekrar aktifleşene kadar bekler."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                btns = self.driver.find_elements(*SELECTORS["devam_et"])
                if btns and btns[0].get_attribute("disabled") is None:
                    print("[INFO] Görsel taraması tamamlandı.")
                    return True
            except Exception:
                pass
            time.sleep(2)
        print(f"[UYARI] Sitenin görsel tarama servisi {timeout} sn içinde yanıt vermedi "
              f"(POST /api/scan-file askıda kalıyor).")
        print("[UYARI] Görsel eklendikten sonra form kilitleniyor ve görseli formdan geri almak "
              "mümkün olmuyor — bu sitenin kendi arızası, bot kaynaklı değil.")
        return False

    # ──────────────────────────────────────────────────────────────────────
    # ADIM 3 — KİŞİSEL BİLGİLER
    # ──────────────────────────────────────────────────────────────────────

    def _fill_personal_step(self):
        print("[INFO] Filling personal profile details...")
        phone = re.sub(r"\D", "", USER_CONFIG["telefon"])
        if phone.startswith("90") and len(phone) > 11:
            phone = phone[2:]
        adres = sanitize_for_site(USER_CONFIG["adres"], ADDRESS_ALLOWED_RE)[:200]
        if len(adres) < 10:
            print(f"[UYARI] config.json'daki adres site için çok kısa ({len(adres)} karakter, en az 10 gerekiyor).")

        self._fill_text_field("name",           USER_CONFIG["ad"],        "ad")
        self._fill_text_field("surname",        USER_CONFIG["soyad"],     "soyad")
        self._fill_text_field("identityNumber", USER_CONFIG["tc_kimlik"], "tc_kimlik")
        self._fill_text_field("phoneNumber",    phone,                    "telefon")
        self._fill_text_field("email",          USER_CONFIG["eposta"],    "eposta")
        self._fill_text_field("address",        adres,                    "adres")

        # KVKK onayları: eski checkAccessPersonelData/expliciptConsent gitti,
        # yerine üç ayrı gizli checkbox geldi (kvkk1/kvkk2/kvkk3).
        print("[INFO] Activating consent checkboxes...")
        for cid in ("kvkk1", "kvkk2", "kvkk3"):
            self._check_hidden_checkbox(cid)

    def _check_hidden_checkbox(self, element_id: str):
        """
        KVKK onay kutuları `hidden` bir <input type=checkbox> + görsel <span> şeklinde.
        Gizli input'a JS click yeterli; olmazsa saran <label>'a tıklıyoruz. Label içindeki
        <button> aydınlatma metni modalını açtığı için ona hiç dokunmuyoruz.
        """
        try:
            els = self.driver.find_elements(By.ID, element_id)
            if not els:
                print(f"[WARNING] Onay kutusu bulunamadı: #{element_id}")
                return
            box = els[0]
            if box.is_selected():
                return
            self._js_click(box)
            time.sleep(0.3)
            if not box.is_selected():
                label = self.driver.find_elements(By.CSS_SELECTOR, f"label[for='{element_id}'] span")
                if label:
                    self._js_click(label[0])
                    time.sleep(0.3)
            print(f"[INFO] Onaylandı: {element_id}" if box.is_selected()
                  else f"[WARNING] Onaylanamadı: {element_id} — elle işaretleyin.")
        except Exception as e:
            print(f"[ERROR] '{element_id}' onaylanırken hata: {e}")

    def _sms_asamasinda_mi(self) -> bool:
        """Sayfa SMS doğrulama adımına geçmiş mi (Input.OTP kutuları görünür mü)?

        Son 'Devam Et' tıklaması başarısız döndüğünde gerçekten gönderilmediğini
        varsaymak yanlış: kullanıcı butona kendisi basmış olabilir, o zaman buton
        DOM'dan kalkıyor ve tıklama haklı olarak başarısız oluyor. OTP kutularının
        varlığı gönderimin objektif kanıtı."""
        try:
            kutular = self.driver.find_elements(*SELECTORS["otp_inputs"])
            return any(k.is_displayed() for k in kutular)
        except Exception as e:
            if tarayici_kapandi_mi(e):
                return False
            print(f"[UYARI] SMS adımı kontrol edilemedi: {kisa_hata(e)}")
            return False

    def _fill_otp(self, sms_code: str):
        """
        SMS kodu artık tek input değil, Ant Design Input.OTP (her hane ayrı kutu).
        Kod girilir ama 'Onayla'ya BASILMAZ — gönderim kararı her zaman kullanıcıda.
        """
        digits = re.sub(r"\D", "", sms_code)
        try:
            boxes = self.driver.find_elements(*SELECTORS["otp_inputs"])
            if not boxes:
                print(f"[WARNING] SMS kutuları bulunamadı. Kodu elle girin: {sms_code}")
                return
            boxes[0].click()
            for i, ch in enumerate(digits[:len(boxes)]):
                boxes[i].send_keys(ch)
                time.sleep(0.1)
            print("[INFO] SMS kodu girildi. Onaylamayı tarayıcıdan siz yapın.")
        except Exception as e:
            print(f"[WARNING] SMS kodu girilemedi ({e}). Elle girin: {sms_code}")

    # ──────────────────────────────────────────────────────────────────────
    # ADIM GEÇİŞLERİ
    # ──────────────────────────────────────────────────────────────────────

    def _dismiss_promo_modal(self):
        """Açılışta çıkan 'HAYAT 112 Mobil Uygulaması' modalı formun üstünü kapatıyor."""
        try:
            modals = self.driver.find_elements(*SELECTORS["promo_modal"])
            if not modals or not modals[0].is_displayed():
                return
            btns = self.driver.find_elements(*SELECTORS["promo_modal_btn"])
            if btns:
                self._js_click(btns[0])
                time.sleep(1)
                print("[INFO] Açılış tanıtım modalı kapatıldı.")
        except Exception as e:
            print(f"[DEBUG] Tanıtım modalı kapatma (önemli değil): {e}")

    def _click_devam_et(self, expected_url_part: str, timeout: int = 20,
                        enable_timeout: int = 15) -> bool:
        """
        Adımın 'Devam Et' butonuna basar ve URL'in bir sonraki adıma geçmesini bekler.
        Buton, form geçerli olana kadar disabled kalıyor; aktifleşmesini bekliyoruz.

        `enable_timeout` detay adımında uzun tutuluyor: açıklamada link varsa site
        linki taramaya yolluyor (POST /api/malware-scanner) ve sonucu 10 saniyede
        bir yokluyor; tarama bitene kadar buton pasif kalıyor.
        """
        try:
            btn = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located(SELECTORS["devam_et"])
            )
        except TimeoutException:
            print("[HATA] 'Devam Et' butonu bulunamadı.")
            return False

        deadline = time.time() + enable_timeout
        while btn.get_attribute("disabled") is not None and time.time() < deadline:
            time.sleep(1)
        if btn.get_attribute("disabled") is not None:
            print("[HATA] 'Devam Et' pasif kaldı — formda eksik/geçersiz alan var.")
            for err in self.driver.find_elements(By.CSS_SELECTOR, ".ant-form-item-explain-error"):
                metin = (err.text or "").strip()
                if metin:
                    print(f"        Sitenin verdiği hata: {metin}")
            return False

        self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.3)
        self._js_click(btn)

        try:
            WebDriverWait(self.driver, timeout).until(EC.url_contains(expected_url_part))
            time.sleep(2)  # yeni adımın render olmasını bekle
            print(f"[INFO] Sonraki adıma geçildi: {expected_url_part}")
            return True
        except TimeoutException:
            print(f"[HATA] Sonraki adıma geçilemedi (URL hâlâ: {self.driver.current_url})")
            return False

    # ──────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────

    def _js_click(self, element):
        self.driver.execute_script("arguments[0].click();", element)

    def _js_fill(self, element, value):
        """
        Inject value into a React-controlled input/textarea via the native setter.
        Fires a SINGLE input event instead of one per character — critical because
        rapid per-char events trigger the site's token-check loop and crash React
        with error #185 (Maximum update depth exceeded).
        """
        self.driver.execute_script("""
            var el = arguments[0];
            var val = arguments[1];
            var proto = (el.tagName === 'TEXTAREA')
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            var nativeSetter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            nativeSetter.call(el, val);
            el.dispatchEvent(new Event('input',  {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
        """, element, value)

    def _wait_for_enabled(self, element_id: str, timeout: int = 8):
        """
        Waits up to `timeout` seconds for an input to lose its `disabled` attribute.
        Short timeout so we don't block the whole automation on a failed API call.
        """
        try:
            def not_disabled(driver):
                try:
                    el = driver.find_element(By.ID, element_id)
                    return el.get_attribute("disabled") is None
                except Exception:
                    return False
            WebDriverWait(self.driver, timeout).until(not_disabled)
            time.sleep(0.5)
            print(f"[INFO] Dropdown hazır: #{element_id}")
        except TimeoutException:
            print(f"[WARNING] Dropdown etkinleşmedi ({timeout}s): #{element_id} — atlanıyor.")

    def _select_ant_dropdown(self, element_id: str, text: str) -> bool:
        """
        Types into an Ant Design search input and selects a matching option.
        Seçimin gerçekten yapıldığını doğrulayıp True/False döndürür.
        Strategy:
          1) Click + type to open dropdown and filter options
          2) Find the option that matches our text (by element.text)
          3) JS-click the matching option — do NOT press ESC after (it deselects!)
          4) Verify the select now shows a value

        Aranan kayıt listede yoksa HİÇBİR ŞEY seçilmez. Eskiden listenin ilk
        seçeneğine düşülüyordu; resmi bir ihbarda bu, olayın geçmediği bir sokağı
        bildirmek demek — boş bırakıp uyarmak daha doğru.
        """
        try:
            element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, element_id))
            )
        except TimeoutException:
            print(f"[UYARI] #{element_id} tıklanamadı (disabled/timeout) — atlanıyor.")
            return False

        search_text = turkish_upper(text.strip())
        # Ek (CADDESİ/SOKAĞI/MAH...) yazılmaz — sitenin kısaltması öngörülemez.
        # Sadece taban isim aranır, seçim aşamasında ek türü eşleştirilir.
        base_text, family = split_address_suffix(search_text)
        # Tire vb. ayraçlar site adıyla uyuşmadığı için aramayı boşluklu yaz.
        typed_text = normalize_separators(base_text)
        base_text_norm = typed_text

        try:
            element.click()
            time.sleep(0.3)
            element.clear()
            for char in typed_text:
                element.send_keys(char)
                time.sleep(0.05)
            time.sleep(2.5)  # Wait for Ant Design to fetch + render options

            # Yalnızca AÇIK popup'ın seçenekleri. Ant kapanan dropdown'ları DOM'dan
            # silmiyor, sadece .ant-select-dropdown-hidden ekliyor; kapsamlamazsak
            # bir önceki alanın (ör. mahalle) gizli seçenekleri de eşleşmeye girip
            # görünmez bir seçeneğe tıklanıyor ve alan boş kalıyor.
            opts = self.driver.find_elements(By.CSS_SELECTOR,
                ".ant-select-dropdown:not(.ant-select-dropdown-hidden) "
                ".ant-select-item-option:not(.ant-select-item-option-disabled)")

            # Seçenekleri değerlendir: önce taban isim + ek türü tam uyumu,
            # yoksa taban isim uyumu. Boş metinli seçenekler atlanır.
            target_opt = None
            partial_opt = None
            for opt in opts:
                opt_text = turkish_upper(opt.text.strip())
                if not opt_text:
                    continue
                opt_base, opt_family = split_address_suffix(opt_text)
                opt_base_norm = normalize_separators(opt_base)
                family_ok = (family is None or opt_family is None or opt_family == family)
                if opt_base_norm == base_text_norm and family_ok:
                    target_opt = opt
                    print(f"[DEBUG] Eşleşen seçenek bulundu: {opt_text!r}")
                    break
                if family_ok and partial_opt is None and (base_text_norm in opt_base_norm or opt_base_norm in base_text_norm):
                    partial_opt = opt

            if target_opt is None and partial_opt is not None:
                target_opt = partial_opt
                print(f"[DEBUG] Kısmi eşleşen seçenek seçiliyor: {turkish_upper(partial_opt.text.strip())!r}")

            if target_opt is not None:
                self._js_click(target_opt)
                # IMPORTANT: do NOT press ESC here — Ant Design would deselect the option!
                time.sleep(1.0)  # Give React time to process selection + fire API call
                secilen = self._dropdown_value(element)
                if secilen:
                    print(f"[INFO] Seçildi: {secilen}")
                    return True
                print(f"[UYARI] '{text}' tıklandı ama alana yerleşmedi.")
                return False

            if opts:
                gorunen = [o.text.strip() for o in opts[:8] if o.text.strip()]
                print(f"[UYARI] '{text}' listede yok. Site bu aramada şunları veriyor: {gorunen}")
            else:
                print(f"[UYARI] '{text}' için site hiç seçenek döndürmedi.")
            return False

        except Exception as e:
            print(f"[HATA] '{text}' seçimi: {e}")
            return False

    def _dropdown_value(self, search_input) -> str:
        """Ant Select'te seçili görünen değer ('' ise seçim yapılmamış).

        Site Ant'ın standart yapısını değiştirmiş: seçili değer alışıldık
        `span.ant-select-selection-item` içinde değil, arama kutusunu saran
        `div.ant-select-content`in title'ında (ve metninde) duruyor. Arama
        kutusunun kendi `value`si seçimden sonra boşaldığı için ona bakılamıyor.
        """
        try:
            return (self.driver.execute_script(
                "var s = arguments[0].closest('.ant-select');"
                "if (!s) return '';"
                "var c = s.querySelector('.ant-select-content');"
                "if (!c) return '';"
                "return (c.getAttribute('title') || c.textContent || '').trim();",
                search_input) or "").strip()
        except Exception:
            return ""

    def _dropdown_has_value(self, search_input) -> bool:
        return bool(self._dropdown_value(search_input))

    def _prevent_form_submit(self):
        """Inject a one-time form submit prevention hook."""
        self.driver.execute_script("""
            if (!window._submitBlocked) {
                window.addEventListener('submit', function(e){ e.preventDefault(); }, true);
                window._submitBlocked = true;
            }
        """)

    def _close_open_dropdowns(self):
        """
        Close any open Ant Design dropdown popup by dispatching a mousedown event.
        IMPORTANT: Do NOT send ESC — it deselects the currently selected option!
        """
        try:
            self.driver.execute_script(
                "document.body.dispatchEvent(new MouseEvent('mousedown', {bubbles:true}));"
            )
            time.sleep(0.5)
            print("[INFO] Açık dropdown popup'ları kapatıldı.")
        except Exception as e:
            print(f"[DEBUG] Dropdown kapat hatası (önemli değil): {e}")

    def _fill_text_field(self, element_id: str, value: str, field_name: str, is_textarea: bool = False):
        """
        Finds a field by ID directly (no blocking wait — elements are pre-rendered in DOM),
        scrolls to it, and fills it. Falls back to JS native setter for React inputs.
        """
        try:
            els = self.driver.find_elements(By.ID, element_id)
            if not els:
                time.sleep(3)  # Brief fallback wait
                els = self.driver.find_elements(By.ID, element_id)
            if not els:
                print(f"[WARNING] '{field_name}' DOM'da bulunamadı: #{element_id}")
                return

            element = els[0]
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", element
            )
            time.sleep(0.3)

            # IMPORTANT: always fill via JS native setter (single input event).
            # Per-character send_keys floods the site's token-check loop and
            # crashes the whole React app (error #185) — see debug session 15.07.2026.
            self._js_fill(element, value)
            actual = element.get_attribute("value") or ""
            # Site may reformat the value (uppercase transform, phone mask like
            # "(533) 270 47 15") — compare only alphanumeric content, Turkish-uppercased.
            norm = lambda s: "".join(c for c in turkish_upper(s) if c.isalnum())
            if norm(actual) != norm(value):
                print(f"[WARNING] JS fill doğrulanamadı ({field_name}): {actual!r} — send_keys deneniyor (yavaş mod)...")
                element.click()
                element.clear()
                for ch in value:
                    element.send_keys(ch)
                    time.sleep(0.08)

            time.sleep(0.2)
            print(f"[INFO] Alan dolduruldu: {field_name} = {value[:30]!r}")
        except Exception as e:
            print(f"[ERROR] '{field_name}' doldurulamadı: {e}")

    def _click_element(self, selector, name: str) -> bool:
        """Tıklama başarılıysa True. Başarısızlığı çağıran taraf görmeli:
        sessizce yutulursa otomasyon, olmamış bir tıklamanın üzerine devam ediyor."""
        try:
            locator = selector if isinstance(selector, tuple) else (By.ID, selector)
            element = WebDriverWait(self.driver, 15).until(
                EC.presence_of_element_located(locator)
            )
            self.driver.execute_script(
                "arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", element
            )
            time.sleep(0.3)
            try:
                element.click()
            except Exception:
                self._js_click(element)
            print(f"[INFO] Tıklandı: {name}")
            return True
        except TimeoutException:
            print(f"[WARNING] '{name}' bulunamadı: {selector}")
            return False
        except Exception as e:
            if tarayici_kapandi_mi(e):
                print(f"[HATA] Tarayıcı penceresi kapanmış — '{name}' tıklanamadı.")
            else:
                print(f"[ERROR] '{name}' tıklanırken hata: {kisa_hata(e)}")
            return False
