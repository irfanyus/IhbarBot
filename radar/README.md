# HLK-LD2450 Radar — ESP32 Bağlantısı

24 GHz mmWave insan takip radarını (HLK-LD2450) doğrudan bir ESP32'ye bağlayıp
hedef koordinatlarını okumak için Arduino sketch'i.

Radar aynı anda **3 hedefe kadar** takip eder ve her biri için x/y koordinatı
(mm), hız (cm/s) ve mesafe çözünürlüğü bildirir — saniyede ~10 kez.

## USB-TTL adaptörüne gerek var mı?

Normal çalışmada **hayır**. Radar doğrudan ESP32'ye bağlanır.

USB-TTL yalnızca şunlar için lazım:

- HLK'nin resmi Windows konfigürasyon aracıyla bölge (zone) ayarı, hassasiyet ayarı
- Baud hızını değiştirmek, fabrika ayarlarına döndürmek
- Firmware güncellemek
- Bir sorunda ham veriyi PC'den doğrulamak

Bunları bir kez yapıp adaptörü kaldırabilirsin.

## Kablolama

Test edilen kart: **MH-ET LIVE / D1 Mini ESP32** (ESP32-WROOM-32).

| Radar pini | Kablo rengi (bu partide) | ESP32 pini |
|---|---|---|
| `GND` | kırmızı | `GND` |
| `TX`  | siyah   | `IO25` |
| `RX`  | sarı    | `IO26` |
| `5V`  | yeşil   | `VCC` (5V rayı) |

### TX/RX'ten emin değilsen

Bu partide TX ve RX'in hangi renge düştüğü kablonun konnektöre giriş sırasından
gözle net okunamıyor. Süreklilik testi siyah = `TX`, sarı = `RX` verdi ve
dokümantasyon buna göre yazıldı.

Sketch hiç çerçeve basmıyorsa **ilk denenecek şey siyah ve sarıyı yer
değiştirmek**. İki hattı ters bağlamak zarar vermez; sadece veri akmaz.

### Kablo renklerine güvenme

Yukarıdaki renk sütunu **yalnızca eldeki kablo için** geçerli; LD2450 ile gelen
4'lü kablonun renk sırası üretim partisine göre değişiyor. Bu partide kırmızının
GND, yeşilin besleme olması standart dışı — renkten gitmek 5V'u bir GPIO'ya
bağlamakla sonuçlanabilir.

Başka bir kablo kullanırsan eşleşmeyi yeniden çıkar:

1. Radar kartını ters çevir, konnektörün yanındaki `5V` / `RX` / `TX` / `GND`
   etiketlerini oku.
2. Multimetreyi süreklilik moduna al; bir ucu kablonun dişi ucundaki bir tele,
   diğer ucu kartın ilgili pin/pad'ine değdirerek eşleşmeyi tek tek çıkar.
3. Notunu al, sonra bağla.

Dikkat edilecekler:

1. **TX ↔ RX çaprazlanır.** Radarın `TX`'i ESP32'nin RX'ine (`IO25`), radarın
   `RX`'i ESP32'nin TX'ine (`IO26`) gider. Düz bağlarsan hiç veri gelmez.
2. **ESP32 tarafında beslemeyi `VCC` (5V) pininden al.** Kartın ön yüzündeki
   `SVP`/`SVN` pinleri besleme değil, GPIO36/GPIO39'dur — oraya bağlama.
   `3.3V` pini de besleme için uygun değil; LD2450 5V ister.
3. **GPIO16/17'den kaçın.** Klasik ESP32'de PSRAM bu iki pini kullanır. Kart
   ayarlarında PSRAM açıksa çekirdek pinleri PSRAM'e ayırır, UART sessizce
   hiçbir şey okumaz — kod hatasız derlenir ve çalışır, bu yüzden teşhisi zor
   bir tuzaktır. Sketch bu yüzden `IO25`/`IO26` kullanıyor. 16/17'de ısrar
   edeceksen önce **Tools → PSRAM → Disabled** yap.
4. **UART0'ı kullanma.** `TXD`/`RXD` etiketli pinler USB seri konsoluna bağlı,
   kod yüklerken çakışır. Sketch UART2'yi kullanır.
5. Seviye çevirici gerekmez; LD2450'nin UART'ı zaten 3.3V mantık seviyesinde.
6. Radar besleme akımı düşüktür (~100 mA tepe), USB'den beslemek yeterli.

Farklı bir kart kullanacaksan `RADAR_RX_PIN` / `RADAR_TX_PIN` değerlerini
değiştirmen yeterli. ESP32'de UART pin matrisi olduğu için hemen her GPIO
kullanılabilir — sadece GPIO6-11 (flash) kullanılmaz, GPIO34-39 yalnızca giriştir
(sadece RX olabilir).

## Kurulum

1. Arduino IDE'de **Boards Manager** → `esp32` (Espressif Systems) paketini kur.
2. Kart olarak **"WEMOS D1 MINI ESP32"** ya da **"ESP32 Dev Module"** seç.
3. `ld2450_esp32/ld2450_esp32.ino` dosyasını aç ve yükle.
4. Seri monitörü **115200** baud ile aç (radar 256000 kullanır, monitör ayrı).

Beklenen çıktı:

```
HLK-LD2450 <-> ESP32
[radar] UART acildi: 256000 baud (RX=GPIO16, TX=GPIO17)
--- #142 ---
  hedef 1: x=  -320 mm  y= 1850 mm  mesafe=1.88 m  aci= -9.8 deg  hiz= -12 cm/s
```

Koordinat sistemi: radarın tam karşısı 0°, **x** sola negatif / sağa pozitif,
**y** her zaman pozitif (radarın önündeki mesafe). Hız yaklaşırken negatif.

## Ayarlar

Sketch'in başındaki blok:

| Ayar | Açıklama |
|---|---|
| `RADAR_RX_PIN` / `RADAR_TX_PIN` | Kullanılan GPIO'lar |
| `RADAR_BAUD` | Fabrika ayarı 256000 |
| `AUTO_BAUD` | 1 ise veri gelmediğinde diğer hızları otomatik dener |
| `PRINT_HZ` | Saniyede kaç satır basılsın |
| `PRINT_EMPTY` | Boş hedef slotlarını da yazdır |

## Sorun giderme

| Belirti | Sebep |
|---|---|
| Hiç veri yok | Önce siyah/sarıyı yer değiştir (TX/RX ters olabilir); sonra GND ortaklığını kontrol et |
| Çöp karakter | Baud yanlış — `AUTO_BAUD 1` yapıp seri monitörü izle |
| Kod yüklenmiyor | Radar `TXD`/`RXD` pinlerine bağlı, UART0'ı meşgul ediyor |
| Hedef hep boş geliyor | Radarın önü kapalı; metal yüzeyden ve duvardan uzaklaştır |
| Değerler saçma | İşaret çözümü yanlış olabilir — LD2450 ikiye tümleyen değil, işaret-büyüklük kodlar |

## Sahada karşılaşılan sorun: kopuk sinyal teli

İlk kurulumda sketch her baud'da `HIC BAYT GELMEDI` bastı. Sırayla elenen adımlar:

1. Kart seçimi (ESP32-S3 seçiliydi, klasik ESP32 olmalıydı) — düzeltildi, yükleme geçti
2. Yükleme hızı 921600'de kopuyordu — 115200'e çekildi
3. TX/RX yer değiştirildi — değişiklik yok
4. Radar besleme pininde 5V ölçüldü — besleme sağlam, GND ortak
5. Radar `TX` pad'inde ~3.3V ölçüldü — radar canlı, hattı sürüyor
6. **`TX` pad'i ile ESP32 ucu arasında süreklilik yok** — sorun bulundu

Kopukluk, radar kablosunun ince telinin dupont jumper muhafazasına
**itilerek** takıldığı noktadaydı. O ek sadece sürtünmeyle tutuyor ve kolayca
temassız kalıyor.

Dikkat edilecek nokta: radarın `TX` pad'inde gerilim ölçmek hattın sürüldüğünü
gösterir, ama o gerilimin ESP32'ye **ulaştığını** göstermez. Tel ortadan kopuksa
radar yine kendi pinini sürer, pad'de yine ~3.3V okunur, ESP32 tarafı boşta
kalır. Bu ikisini ayırmanın tek yolu uçtan uca süreklilik ölçmektir.

Kalıcı çözüm: eki lehimleyip makaronla izole etmek, ya da kabloyu atlayıp
radar kartındaki `5V/RX/TX/GND` delikli pad'lerine doğrudan tel lehimlemek.

## Protokol notu

Hedef verisi 30 baytlık sabit çerçeve halinde gelir:

```
AA FF 03 00 | hedef1 (8B) | hedef2 (8B) | hedef3 (8B) | 55 CC
```

Her hedef: `x (2B) | y (2B) | hız (2B) | çözünürlük (2B)`, little-endian.

Koordinat ve hız alanları **işaret-büyüklük** kodludur: en anlamlı bit 1 ise
değer pozitif, 0 ise negatiftir. Doğrudan `int16_t`'ye cast etmek yanlış sonuç
verir — sketch'teki `decodeSigned()` bunu doğru çözer. Boş hedef slotu 8 baytın
tamamı sıfır olarak gelir.

## Anten hakkında

Radarın 24 GHz antenleri kartın ön yüzüne baskıdır (altın renkli dikdörtgenler).
Radar tarafında veri almak için harici anten takman gerekmez.

Kartın arka yüzünde ayrıca bir u.FL/IPEX soketi bulunuyor. Kutudan çıkan ince
siyah PCB anten bu sokete uyar, ancak çalışması için gerekli değil — bu sketch
antensiz de veri okur.

D1 Mini ESP32 kartında u.FL soketi yoktur, dahili PCB anten kullanır; o anten
ESP32 tarafına takılamaz.
