/*
 * HLK-LD2450 24 GHz mmWave radar  ->  ESP32 (Arduino)
 *
 * Radarin UART'indan gelen 30 baytlik hedef cercevesini cozer ve
 * seri monitore hedeflerin x/y koordinatini, hizini, mesafesini ve
 * acisini basar. LD2450 ayni anda en fazla 3 hedef bildirir.
 *
 * Kablolama (USB-TTL'e gerek yok):
 *   radar GND -> ESP32 GND
 *   radar TX  -> RADAR_RX_PIN (IO16)     <- caprazlanir
 *   radar RX  -> RADAR_TX_PIN (IO17)     <- caprazlanir
 *   radar 5V  -> ESP32 VCC (5V rayi)
 *
 * Elimizdeki kabloda olculen renk sirasi (sureklilik testiyle dogrulandi):
 *   kirmizi = GND        siyah = TX (radarin cikisi)
 *   sari    = RX         yesil = 5V
 * Bu sira uretici partisine gore degisir; baska bir kabloda renkten
 * gitme, her seferinde karttaki ipek baski etiketini esas al.
 * Hic cerceve gelmezse ilk deneme: siyah ve sariyi yer degistir (TX/RX
 * ters baglanmasi zarar vermez, sadece veri akmaz).
 *
 * ESP32 tarafinda besleme icin VCC etiketli pini kullan; kartta 3.3V pini de
 * var ve LD2450 orada kararsiz calisir.
 *
 * Seviye cevirici gerekmez, LD2450'nin UART'i 3.3V mantik seviyesinde.
 */

// ------------------------------ AYARLAR ------------------------------

// ESP32'nin RX'i  <- radarin TX'i (siyah kablo)
#define RADAR_RX_PIN   16
// ESP32'nin TX'i  -> radarin RX'i (sari kablo)
#define RADAR_TX_PIN   17

// LD2450 fabrika ayari 256000. Konfigurasyon aracindan degistirdiysen guncelle.
#define RADAR_BAUD     256000

// 1 yaparsan, gecerli cerceve gelmediginde diger yaygin hizlari dener.
#define AUTO_BAUD      1

// Seri monitore saniyede kac satir basilsin (radar ~10 Hz veri uretir).
#define PRINT_HZ       4

// Bos slotlari da yazdirmak icin 1 yap.
#define PRINT_EMPTY    0

// ---------------------------------------------------------------------

// Klasik ESP32'de UART2 bostur. ESP32-C3/C6 gibi 2 UART'li yongalarda
// bu satiri Serial1 yap ve pinleri bos GPIO'lardan sec.
#define RadarSerial Serial2

// LD2450 cerceve formati: AA FF 03 00 | 3 x 8 bayt hedef | 55 CC  = 30 bayt
static const uint8_t FRAME_HEADER[4] = {0xAA, 0xFF, 0x03, 0x00};
static const uint8_t FRAME_TAIL[2]   = {0x55, 0xCC};
static const uint8_t FRAME_LEN       = 30;

#if AUTO_BAUD
static const uint32_t BAUD_LIST[] = {RADAR_BAUD, 115200, 921600, 460800, 57600, 38400, 19200, 9600};
static const uint8_t  BAUD_COUNT  = sizeof(BAUD_LIST) / sizeof(BAUD_LIST[0]);
static uint8_t        baudIndex   = 0;
#endif

struct Target {
  bool     active;
  int16_t  x_mm;        // sola negatif, saga pozitif
  int16_t  y_mm;        // radarin onunde, daima pozitif
  int16_t  speed_cms;   // yaklasan negatif, uzaklasan pozitif
  uint16_t res_mm;      // mesafe cozunurlugu
};

static uint8_t  frameBuf[FRAME_LEN];
static uint8_t  frameIdx      = 0;
static uint32_t lastFrameMs   = 0;
static uint32_t lastPrintMs   = 0;
static uint32_t frameCount    = 0;

/*
 * LD2450 koordinat ve hizlari isaret-buyukluk (sign-magnitude) kodlar:
 * en anlamli bit 1 ise deger pozitif, 0 ise negatiftir. Ikiye tumleyen degil,
 * bu yuzden dogrudan int16_t'ye cast etmek yanlis sonuc verir.
 */
static int16_t decodeSigned(uint8_t lo, uint8_t hi) {
  uint16_t raw = (uint16_t)lo | ((uint16_t)hi << 8);
  int16_t  mag = (int16_t)(raw & 0x7FFF);
  return (raw & 0x8000) ? mag : (int16_t)-mag;
}

static void startRadarSerial(uint32_t baud) {
  RadarSerial.end();
  RadarSerial.begin(baud, SERIAL_8N1, RADAR_RX_PIN, RADAR_TX_PIN);
  Serial.printf("[radar] UART acildi: %lu baud (RX=GPIO%d, TX=GPIO%d)\n",
                (unsigned long)baud, RADAR_RX_PIN, RADAR_TX_PIN);
}

static void printTargets(const Target t[3]) {
  Serial.printf("--- #%lu ---\n", (unsigned long)frameCount);
  for (uint8_t i = 0; i < 3; i++) {
    if (!t[i].active) {
#if PRINT_EMPTY
      Serial.printf("  hedef %u: -\n", i + 1);
#endif
      continue;
    }
    float dist_m = sqrtf((float)t[i].x_mm * t[i].x_mm +
                         (float)t[i].y_mm * t[i].y_mm) / 1000.0f;
    // Radarin tam karsisi 0 derece; sol negatif, sag pozitif.
    float angle_deg = atan2f((float)t[i].x_mm, (float)t[i].y_mm) * 180.0f / PI;

    Serial.printf("  hedef %u: x=%5d mm  y=%5d mm  mesafe=%.2f m  aci=%+6.1f deg  hiz=%+4d cm/s\n",
                  i + 1, t[i].x_mm, t[i].y_mm, dist_m, angle_deg, t[i].speed_cms);
  }
}

static void handleFrame(const uint8_t *f) {
  frameCount++;
  lastFrameMs = millis();

  Target targets[3];
  for (uint8_t i = 0; i < 3; i++) {
    const uint8_t *p = f + 4 + i * 8;

    // Bos slot 8 baytin tamami sifir olarak gelir.
    bool empty = true;
    for (uint8_t j = 0; j < 8; j++) {
      if (p[j] != 0x00) { empty = false; break; }
    }

    targets[i].active    = !empty;
    targets[i].x_mm      = empty ? 0 : decodeSigned(p[0], p[1]);
    targets[i].y_mm      = empty ? 0 : decodeSigned(p[2], p[3]);
    targets[i].speed_cms = empty ? 0 : decodeSigned(p[4], p[5]);
    targets[i].res_mm    = empty ? 0 : (uint16_t)(p[6] | ((uint16_t)p[7] << 8));
  }

  uint32_t now = millis();
  if (now - lastPrintMs >= (1000 / PRINT_HZ)) {
    lastPrintMs = now;
    printTargets(targets);
  }
}

// Gelen baytlari cerceve basligina hizalayarak toplar.
static void feed(uint8_t b) {
  if (frameIdx < 4) {
    if (b == FRAME_HEADER[frameIdx]) {
      frameBuf[frameIdx++] = b;
    } else {
      // Hizalama bozuldu. Bayt yeni bir baslangic olabilir, ona gore sifirla.
      frameIdx = (b == FRAME_HEADER[0]) ? 1 : 0;
      if (frameIdx == 1) frameBuf[0] = b;
    }
    return;
  }

  frameBuf[frameIdx++] = b;
  if (frameIdx < FRAME_LEN) return;

  frameIdx = 0;
  if (frameBuf[28] == FRAME_TAIL[0] && frameBuf[29] == FRAME_TAIL[1]) {
    handleFrame(frameBuf);
  }
  // Kuyruk tutmuyorsa cerceve bozuk; sessizce atlanir, bir sonrakine bakilir.
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println();
  Serial.println("HLK-LD2450 <-> ESP32");

  startRadarSerial(RADAR_BAUD);
  lastFrameMs = millis();
}

void loop() {
  while (RadarSerial.available()) {
    feed((uint8_t)RadarSerial.read());
  }

  // 3 saniyedir gecerli cerceve yoksa ya kablolama ya da baud yanlis.
  if (millis() - lastFrameMs > 3000) {
    lastFrameMs = millis();
#if AUTO_BAUD
    baudIndex = (baudIndex + 1) % BAUD_COUNT;
    Serial.println("[radar] Veri yok, baska bir baud deneniyor...");
    startRadarSerial(BAUD_LIST[baudIndex]);
    frameIdx = 0;
#else
    Serial.println("[radar] Veri yok. TX/RX caprazlamasini, GND ortakligini ve baud degerini kontrol et.");
#endif
  }
}
