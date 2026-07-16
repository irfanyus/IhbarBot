import time
import os
import json
import sys
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# ==========================================
# 1. TURKISH UPPERCASE HELPER
# ==========================================
def turkish_upper(text: str) -> str:
    if not text:
        return ""
    mapping = {"i": "İ", "ı": "I", "ğ": "Ğ", "ü": "Ü", "ş": "Ş", "ö": "Ö", "ç": "Ç"}
    return "".join(mapping.get(c, c.upper()) for c in text)


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
# 2b. ADDRESS SUFFIX HANDLING
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


# ==========================================
# 3. SELECTORS
# ==========================================
SELECTORS = {
    "guvenlik_emniyet_radio": (By.XPATH, "//label[contains(@class,'ant-radio-wrapper') and contains(.,'Emniyet')]"),
    "gonder_button":          (By.XPATH, "//button[@type='submit']"),
}


class IhbarFormFiller:
    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self.wait = WebDriverWait(self.driver, 20)

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────

    def fill_form(self, address_info: dict, video_path: str, description_text: str, wait_callback=None):
        target_url = "https://ihbar.ng112.gov.tr"
        print(f"[INFO] Navigating to {target_url}...")
        self.driver.get(target_url)
        time.sleep(3)

        # ── 1. Location Dropdowns ─────────────────────────────────────
        print("[INFO] Selecting location address details...")

        if address_info.get("il") not in (None, "Bilinmiyor"):
            self._select_ant_dropdown("cityDropdown", address_info["il"])
            self._wait_for_enabled("districtDropdown", timeout=8)

        if address_info.get("ilçe") not in (None, "Bilinmiyor"):
            self._select_ant_dropdown("districtDropdown", address_info["ilçe"])
            self._wait_for_enabled("neighboorhoodDropdown", timeout=8)

        if address_info.get("mahalle") not in (None, "Bilinmiyor"):
            self._select_ant_dropdown("neighboorhoodDropdown", address_info["mahalle"])
            self._wait_for_enabled("streetDropdown", timeout=8)

        if address_info.get("sokak") not in (None, "Bilinmiyor"):
            self._select_ant_dropdown("streetDropdown", address_info["sokak"])

        # Close any open dropdown popup (mousedown, NOT ESC — ESC deselects in Ant Design)
        self._close_open_dropdowns()
        time.sleep(1)

        # ── 2. Güvenlik Birimi Radio ──────────────────────────────────
        print("[INFO] Selecting Emniyet as safety institution...")
        self._click_element(SELECTORS["guvenlik_emniyet_radio"], "Emniyet Radio")

        # ── 3. Olay Açıklaması ────────────────────────────────────────
        print("[INFO] Writing incident description...")
        self._fill_text_field("description", description_text, "vaka_description", is_textarea=True)

        # ── 4. Dosya Yükleme ─────────────────────────────────────────
        if video_path and video_path != "VIDEO_BULUNAMADI":
            abs_path = os.path.abspath(video_path)
            print(f"[INFO] Attaching file: {abs_path}")
            self._upload_file(abs_path)
        else:
            print("[WARNING] Yüklenecek dosya bulunamadı. Lütfen manuel ekleyin.")

        # ── 5. KVKK Onayları ─────────────────────────────────────────
        print("[INFO] Activating consent checkboxes...")
        self._click_by_id("checkAccessPersonelData", "KVKK Veri İzni")
        self._click_by_id("expliciptConsent", "KVKK Açık Rıza")

        # ── 6. Kişisel Bilgiler ───────────────────────────────────────
        print("[INFO] Filling personal profile details...")
        self._fill_text_field("name",           USER_CONFIG["ad"],                      "ad")
        self._fill_text_field("surname",         USER_CONFIG["soyad"],                  "soyad")
        self._fill_text_field("identityNumber",  USER_CONFIG["tc_kimlik"],              "tc_kimlik")
        self._fill_text_field("phoneNumber",     USER_CONFIG["telefon"].replace(" ",""), "telefon")
        self._fill_text_field("address",         USER_CONFIG["adres"],                  "adres")
        self._fill_text_field("email",           USER_CONFIG["eposta"],                 "eposta")

        # ── 7. hCaptcha Bekleme ───────────────────────────────────────
        print("\n[WAIT] Form doldurma tamamlandı.")
        print("[WAIT] Lütfen tarayıcıda hCaptcha doğrulamasını elle yapın.")
        if wait_callback:
            wait_callback("hcaptcha", "Robot doğrulamasını tamamlayıp 'Devam Et' butonuna tıklayın.")
        else:
            input("hCaptcha'yı tamamlayıp ENTER'a basın...")

        # ── 8. Gönder Butonu ─────────────────────────────────────────
        print("[INFO] Gönder butonuna tıklanıyor...")
        self._click_element(SELECTORS["gonder_button"], "Gönder Butonu")

        # ── 9. SMS Doğrulama ─────────────────────────────────────────
        print("\n[WAIT] SMS doğrulama kodu bekleniyor...")
        sms_code = ""
        if wait_callback:
            sms_code = wait_callback("sms", "SMS kodunu girin (boş bırakabilirsiniz):")
        else:
            sms_code = input("SMS kodu (boş=geç): ").strip()

        if sms_code:
            for guess in ['smsCode', 'sms', 'code', 'verificationCode', 'otp']:
                try:
                    el = self.driver.find_element(By.ID, guess)
                    el.clear(); el.send_keys(sms_code)
                    print("[INFO] SMS kodu girildi.")
                    break
                except Exception:
                    pass
            else:
                print(f"[WARNING] SMS alanı bulunamadı. Manuel girin: {sms_code}")

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

    def _select_ant_dropdown(self, element_id: str, text: str):
        """
        Types into an Ant Design search input and selects a matching option.
        Strategy:
          1) Click + type to open dropdown and filter options
          2) Find the option that matches our text (by element.text)
          3) JS-click the matching option — do NOT press ESC after (it deselects!)
          4) Fallback: ARROW_DOWN + ENTER if no options visible
        """
        try:
            element = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, element_id))
            )
        except TimeoutException:
            print(f"[UYARI] #{element_id} tıklanamadı (disabled/timeout) — atlanıyor.")
            return

        search_text = turkish_upper(text.strip())
        # Ek (CADDESİ/SOKAĞI/MAH...) yazılmaz — sitenin kısaltması öngörülemez.
        # Sadece taban isim aranır, seçim aşamasında ek türü eşleştirilir.
        base_text, family = split_address_suffix(search_text)

        try:
            element.click()
            time.sleep(0.3)
            element.clear()
            for char in base_text:
                element.send_keys(char)
                time.sleep(0.05)
            time.sleep(2.5)  # Wait for Ant Design to fetch + render options

            # Find all visible options
            option_xpath = "//*[contains(@class,'ant-select-item-option') and not(contains(@class,'disabled'))]"
            opts = self.driver.find_elements(By.XPATH, option_xpath)

            # Seçenekleri değerlendir: önce taban isim + ek türü tam uyumu,
            # yoksa taban isim uyumu. Boş metinli seçenekler atlanır.
            target_opt = None
            partial_opt = None
            for opt in opts:
                opt_text = turkish_upper(opt.text.strip())
                if not opt_text:
                    continue
                opt_base, opt_family = split_address_suffix(opt_text)
                family_ok = (family is None or opt_family is None or opt_family == family)
                if opt_base == base_text and family_ok:
                    target_opt = opt
                    print(f"[DEBUG] Eşleşen seçenek bulundu: {opt_text!r}")
                    break
                if family_ok and partial_opt is None and (base_text in opt_base or opt_base in base_text):
                    partial_opt = opt

            if target_opt is None and partial_opt is not None:
                target_opt = partial_opt
                print(f"[DEBUG] Kısmi eşleşen seçenek seçiliyor: {turkish_upper(partial_opt.text.strip())!r}")

            if target_opt is None and opts:
                # Fallback: take the first option if text matching fails
                target_opt = opts[0]
                print(f"[WARNING] '{text}' için exact match bulunamadı, ilk seçenek seçiliyor.")

            if target_opt:
                self._js_click(target_opt)
                print(f"[INFO] Seçildi (JS click): {text}")
                # IMPORTANT: do NOT press ESC here — Ant Design would deselect the option!
                time.sleep(1.0)  # Give React time to process selection + fire API call
                return

            # Last fallback: keyboard navigation
            print(f"[WARNING] Dropdown listesi boş, ENTER ile seçiliyor: {text}")
            self._prevent_form_submit()
            element.send_keys(Keys.ARROW_DOWN)
            time.sleep(0.3)
            element.send_keys(Keys.ENTER)
            # IMPORTANT: do NOT press ESC after ENTER either!
            time.sleep(1.0)
            print(f"[INFO] Seçildi (ENTER): {text}")

        except Exception as e:
            print(f"[HATA] '{text}' seçimi: {e}")

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

    def _click_by_id(self, element_id: str, name: str):
        """
        Find and click an element by ID directly (no blocking wait).
        Elements are pre-rendered in the DOM so no WebDriverWait needed.
        """
        try:
            els = self.driver.find_elements(By.ID, element_id)
            if not els:
                time.sleep(2)  # Small fallback wait
                els = self.driver.find_elements(By.ID, element_id)
            if els:
                self.driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'smooth',block:'center'});", els[0]
                )
                time.sleep(0.3)
                self._js_click(els[0])
                print(f"[INFO] Tıklandı: {name}")
            else:
                print(f"[WARNING] '{name}' DOM'da bulunamadı (#{element_id})")
        except Exception as e:
            print(f"[ERROR] '{name}' tıklanırken hata: {e}")

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
            if is_textarea:
                # Site yasaklı karakterler: * < > ^ | ; { } [ ] \
                safe = value.replace("\n", " - ")
                for ch in "*<>^|;{}[]\\":
                    safe = safe.replace(ch, " ")
            else:
                safe = value
            self._js_fill(element, safe)
            actual = element.get_attribute("value") or ""
            # Site may reformat the value (uppercase transform, phone mask like
            # "(533) 270 47 15") — compare only alphanumeric content, Turkish-uppercased.
            norm = lambda s: "".join(c for c in turkish_upper(s) if c.isalnum())
            if norm(actual) != norm(safe):
                print(f"[WARNING] JS fill doğrulanamadı ({field_name}): {actual!r} — send_keys deneniyor (yavaş mod)...")
                element.click()
                element.clear()
                for ch in safe:
                    element.send_keys(ch)
                    time.sleep(0.08)

            time.sleep(0.2)
            print(f"[INFO] Alan dolduruldu: {field_name} = {value[:30]!r}")
        except Exception as e:
            print(f"[ERROR] '{field_name}' doldurulamadı: {e}")

    def _click_element(self, selector, name: str):
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
        except TimeoutException:
            print(f"[WARNING] '{name}' bulunamadı: {selector}")
        except Exception as e:
            print(f"[ERROR] '{name}' tıklanırken hata: {e}")

    def _upload_file(self, abs_file_path: str):
        """
        Uploads a file to the hidden <input type='file'>.
        Uses find_elements directly (no blocking wait) since the element is always in the DOM.
        Makes the element visible via JS before sending the absolute path.
        """
        try:
            file_inputs = self.driver.find_elements(By.XPATH, "//input[@type='file']")
            if not file_inputs:
                time.sleep(2)
                file_inputs = self.driver.find_elements(By.XPATH, "//input[@type='file']")
            if not file_inputs:
                print("[WARNING] Dosya input'u DOM'da bulunamadı! Lütfen manuel yükleyin.")
                return

            file_input = file_inputs[0]
            # Remove display:none so Selenium can interact with it
            self.driver.execute_script("""
                arguments[0].style.display  = 'block';
                arguments[0].style.opacity  = '1';
                arguments[0].style.position = 'fixed';
                arguments[0].style.top      = '0';
                arguments[0].style.left     = '0';
                arguments[0].style.zIndex   = '999999';
            """, file_input)
            time.sleep(0.3)
            file_input.send_keys(abs_file_path)
            print(f"[INFO] Dosya yüklendi: {abs_file_path}")
        except Exception as e:
            print(f"[ERROR] Dosya yükleme hatası: {e}. Lütfen manuel yükleyin.")