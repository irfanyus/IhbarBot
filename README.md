# İhbarBot — 112 Trafik İhbar Asistanı

Araç kamerası (dash-cam) videolarından trafik ihlali ihbarını yarı otomatik hale getiren bir araç. Videodaki GPS koordinatlarını ve tarih/saati OCR ile okur, koordinatlardan adresi çözer ve [ihbar.ng112.gov.tr](https://ihbar.ng112.gov.tr) üzerindeki resmi ihbar formunu sizin yerinize doldurur.

> **Not:** Bot formu yalnızca **doldurur**. hCaptcha doğrulamasını ve SMS onayını siz elle yaparsınız; gönderim her zaman sizin kontrolünüzdedir.

## Neler yapar?

- `videolar/` klasöründeki videoyu otomatik bulur
- Dosya adından plakayı okur (örn. `34ABC123.mp4` → plaka `34ABC123`; birden çok plaka boşlukla ayrılabilir: `34ABC123 06XYZ789.mp4`)
- Video karelerinden macOS Vision OCR ile GPS koordinatı ve tarih/saat çıkarır
- Koordinatlardan il / ilçe / mahalle / sokak bilgisini çözer (OpenStreetMap Nominatim)
- Chrome'u açıp ihbar formunu doldurur: adres, güvenlik birimi, olay açıklaması, video eki, KVKK onayları ve kişisel bilgiler
- hCaptcha ve SMS adımlarında durup sizi bekler

## Gereksinimler

- **macOS** (OCR için yerleşik Vision API kullanılır — `swift` komutu, Xcode Command Line Tools ile gelir)
- **Python 3.9+**
- **Google Chrome** (ChromeDriver'ı Selenium kendisi indirir)
- **ffmpeg** (videodan kare çıkarmak için): `brew install ffmpeg`

## Kurulum

```bash
git clone <repo-url>
cd IhbarBot

# Sanal ortam oluştur ve bağımlılıkları kur
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Kişisel bilgi dosyanızı oluşturun
cp config.example.json config.json
```

Ardından `config.json` dosyasını açıp **kendi** bilgilerinizle doldurun (form bu bilgilerle gönderilir):

```json
{
    "ad": "ADINIZ",
    "soyad": "SOYADINIZ",
    "tc_kimlik": "11111111111",
    "telefon": "5xxxxxxxxx",
    "adres": "İKAMET ADRESİNİZ",
    "eposta": "ornek@eposta.com"
}
```

> `config.json` `.gitignore`'dadır; kişisel bilgileriniz repoya gitmez.

## Kullanım

1. İhbar edeceğiniz videoyu `videolar/` klasörüne koyun. Dosya adını plaka yapın (örn. `34ABC123.mp4`).

2. Arayüzü başlatın:

```bash
source venv/bin/activate
python3 app.py
```

   veya Finder'dan `İhbarBot.command` dosyasına çift tıklayın. Terminal tabanlı sürüm için: `python3 main.py`

3. Bot videoyu tarar; koordinat, tarih/saat ve plakayı otomatik doldurur. Okunamayan alanları elle girin, "Adresi Sorgula" ile adresi kontrol edin.

4. **İHBAR OTOMASYONUNU BAŞLAT**'a tıklayın. Chrome açılır ve form doldurulur.

5. Tarayıcıda **hCaptcha'yı elle çözün**, ardından arayüzden "Devam Et"e basın.

6. Telefonunuza gelen **SMS kodunu** girin ve onaylayın.

## Dosya yapısı

| Dosya | Görev |
|---|---|
| `app.py` | Tkinter grafik arayüzü (önerilen giriş noktası) |
| `main.py` | Terminal (CLI) sürümü |
| `form_filler.py` | Selenium ile form doldurma mantığı |
| `ocr_helper.py` | ffmpeg ile kare çıkarma + OCR sonuçlarını ayrıştırma |
| `ocr_helper.swift` | macOS Vision API ile metin tanıma |
| `geocoder.py` | Koordinat → adres çözümleme (Nominatim) |
| `config.example.json` | Kişisel bilgi şablonu (`config.json` olarak kopyalayın) |

## Bilinen incelikler (ihbar.ng112.gov.tr)

- Form alanları React kontrollüdür; karakter karakter yazmak sitenin token kontrol döngüsünü tetikleyip sayfayı çökertir (React error #185). Bu yüzden alanlar tek seferde JS ile doldurulur.
- Açıklama alanında `* < > ^ | ; { } [ ] \` karakterleri yasaktır; bot bunları otomatik temizler.
- Ant Design dropdown'larında ESC tuşu seçimi iptal eder; bot bu nedenle popup'ları mousedown ile kapatır.
- Adres eklerinin kısaltmaları öngörülemez (`CADDESİ` → `CD.` gelebilir); bot taban ismiyle arayıp ek türüne göre eşleştirir.

## Sorumluluk reddi

Bu araç, resmi ihbar sürecini kolaylaştırmak için yazılmış kişisel bir yardımcıdır. Gönderilen her ihbarın içeriğinden ve doğruluğundan kullanıcı sorumludur. Asılsız ihbar yapmak suçtur. Araç hCaptcha veya SMS doğrulamasını atlatmaz; her gönderim kullanıcının elle onayıyla gerçekleşir.
