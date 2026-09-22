# -*- coding: utf-8 -*-
"""Trafik ihlallerinin 2918 sayılı KTK'daki karşılığını bulan katalog.

Kullanıcının serbest yazdığı olay detayı ("kırmızı ışık ihlali") burada
anahtar kelimeyle eşleştirilip ihbar açıklamasına kanuni dayanak olarak
ekleniyor: madde/bent + rehberdeki resmî ihlal tanımı + ceza puanı.

Maddeler ve tanımlar EGM'nin yayımladığı resmî ceza rehberinden birebir
alındı (bkz. KAYNAK_URL). Tutarlar bilerek ihbar metnine yazılmıyor:
2026'da 7574 sayılı Kanun'la birçok kalem sabit tutara bağlandı ve bunların
bir kısmı (kırmızı ışık, cep telefonu) sürücünün son bir yıldaki tekrar
sayısına göre katlanıyor. Kaçıncı ihlal olduğunu bilemediğimiz için resmî
bir ihbara tutar yazmak yanlış bilgi üretir; tutarlar yalnızca kullanıcıya
bilgi olsun diye ekranda gösteriliyor.
"""

import re
from dataclasses import dataclass, field

KANUN_ADI = "2918 sayılı Karayolları Trafik Kanunu"
REHBER_YILI = 2026
KAYNAK_URL = ("https://www.trafik.gov.tr/kurumlar/trafik.gov.tr/"
              "trafik-para-cezasi/2026/2026-YILI-TRAFIK-IDARI-PARA-CEZA-REHBERI.pdf")


@dataclass(frozen=True)
class Ihlal:
    anahtar: str          # iç kimlik
    etiket: str           # GUI/CLI'da görünen kısa ad
    madde: str            # "47/1-b"
    resmi_tanim: str      # rehberdeki resmî ifade
    ceza_puani: int = None
    tutar: str = None     # yalnızca bilgi amaçlı, ihbar metnine yazılmaz
    kelimeler: tuple = field(default_factory=tuple)
    # "park" / "duraklama" / None(sürüş). eslestir() bu grupla filtreliyor:
    # bkz. DURAN_ARAC_BELIRTECLERI.
    grup: str = None

    def dayanak_metni(self) -> str:
        """İhbar açıklamasına eklenecek tek satırlık kanuni dayanak."""
        metin = f"Kanuni dayanak: {KANUN_ADI} madde {self.madde} - {self.resmi_tanim}"
        if self.ceza_puani:
            metin += f" ({self.ceza_puani} ceza puanı)"
        return metin + "."

    def kisa_ozet(self) -> str:
        """Liste kutusunda tek satıra sığan kısa hâli (resmî tanım yerine etiket)."""
        parcalar = [f"KTK {self.madde}", self.etiket]
        if self.ceza_puani:
            parcalar.append(f"{self.ceza_puani} puan")
        if self.tutar:
            parcalar.append(self.tutar)
        return " - ".join(parcalar)

    def ozet(self) -> str:
        """Ekranda gösterilecek özet; burada tutarı da veriyoruz."""
        parcalar = [f"KTK {self.madde}", self.resmi_tanim]
        if self.ceza_puani:
            parcalar.append(f"{self.ceza_puani} ceza puanı")
        if self.tutar:
            parcalar.append(f"{REHBER_YILI}: {self.tutar}")
        return " - ".join(parcalar)


# Sıra önemli değil; eşleşme en uzun anahtar kelimeye göre yapılıyor.
KATALOG = (
    Ihlal("kirmizi_isik", "Kırmızı ışık ihlali", "47/1-b",
          "Kırmızı ışık kuralına uymamak", 20,
          "1. ihlalde 5.000 TL, bir yıl içindeki tekrarlarda 80.000 TL'ye kadar",
          ("kirmizi isik", "kirmizi isikta", "kirmiziya", "isik ihlali", "kirmizi")),
    Ihlal("trafik_isareti", "Trafik levhası/yer işaretlemesi ihlali", "47/1-c",
          "Trafik işaret levhaları, cihazları ve yer işaretlemeleri ile belirtilen "
          "veya gösterilen hususlara uymamak", 20, "1.000 TL",
          ("levha", "trafik isareti", "yer isaretlemesi", "yasak isaret", "durak cizgisi",
           "girisi olmayan yol", "girilmez")),
    Ihlal("gorevli_isareti", "Görevlinin uyarı ve işaretine uymamak", "47/1-a",
          "Trafiği düzenleme ve denetimle görevli trafik kolluğu veya özel kıyafetli "
          "veya işaret taşıyan diğer yetkili kişilerin uyarı ve işaretlerine uymamak",
          20, "3.000 TL",
          ("gorevli", "polis isareti", "trafik polisi", "dur ihtari")),

    Ihlal("emniyet_seridi", "Emniyet şeridi / banket ihlali", "46/2-f",
          "Trafik kazası, arıza halleri, acil yardım, kurtarma, kar mücadelesi, kaza "
          "incelemesi, genel güvenlik ve asayişin sağlanması gibi durumlar dışında "
          "emniyet şeritlerini ve banketleri kullanmak",
          None, "20.000 TL",
          ("emniyet seridi", "emniyet seridinde", "banket", "banketten")),
    Ihlal("makas", "Makas atma (ardı ardına şerit değiştirme)", "46/2-g",
          "Trafiği aksatacak veya tehlikeye sokacak şekilde ardı ardına birden fazla "
          "şerit değiştirmek",
          None, "90.000 TL ve 60 gün sürücü belgesine el koyma",
          ("makas", "makas atma", "makas atti", "ardi ardina serit")),
    Ihlal("tehlikeli_serit", "Tehlikeli şerit değiştirme", "46/2-c",
          "Trafiği aksatacak veya tehlikeye düşürecek şekilde şerit değiştirmek",
          20, "10.000 TL",
          ("tehlikeli serit", "ani serit", "aniden serit", "onume kirdi", "onumu kesti",
           "sikistirdi", "sikistirma")),
    Ihlal("yolun_sagindan_gitmeme", "Yolun sağından gitmemek / karşı şeride geçmek", "46/2-a",
          "Aksine bir işaret bulunmadıkça aracı, gidiş yönüne göre yolun sağından, "
          "çok şeritli yollarda ise yol ve trafik durumuna göre hızının gerektirdiği "
          "şeritten sürmemek", 20, "5.000 TL",
          ("ters serit", "ters seride", "ters seritte", "karsi serit", "karsi seride",
           "karsi seritte", "karsi yona gecti", "soldan gitti")),
    Ihlal("serit_ihlali", "Şerit izleme/değiştirme kuralı ihlali", "56/1-a",
          "Şerit izleme ve değiştirme kurallarına uymamak", 20, "1.000 TL",
          ("serit ihlali", "serit degistirme", "seritler uzerinde", "iki serit",
           "serit ortasinda", "serit")),
    Ihlal("sol_serit_isgali", "Sol şeridi sürekli işgal", "46/2-d",
          "Gidişe ayrılan en soldaki şeridi sürekli olarak işgal etmek", 20, "5.000 TL",
          ("sol serit isgal", "en sol seridi", "sol seritte yavas", "soldan yavas")),
    Ihlal("yakin_takip", "Yakın takip", "56/1-c",
          "Önlerinde giden araçları Yönetmelikte belirtilen güvenli ve yeterli bir "
          "mesafeden izlememek (Yakın takip)", 20, "5.000 TL",
          ("yakin takip", "dipçik", "dipcik", "arkama yapisti", "takip mesafesi",
           "cok yakin")),
    Ihlal("guvenli_mesafe", "Güvenli takip mesafesini bırakmamak", "52/1-c",
          "Diğer bir aracı izlerken, hızını kullandığı aracın yük ve teknik özelliğine, "
          "görüş, yol, hava ve trafik durumunun gerektirdiği şartlara uydurmadan "
          "Yönetmelikte belirlenen güvenli mesafeyi bırakmamak", 20, "1.246 TL",
          ("guvenli mesafe", "mesafe birakma")),

    Ihlal("ters_yon_tek", "Tek yönlü yolda ters yön", "46/2-h",
          "Tek yönlü karayollarında aracı ters istikamette sürmek", None, "10.000 TL",
          ("tek yonlu", "tek yonde ters", "tek yonlu yolda ters")),
    Ihlal("ters_yon_bolunmus", "Bölünmüş yolda ters yön", "46/2-i",
          "Yerleşim yeri içerisinde bölünmüş karayollarında aracı ters istikamette sürmek",
          None, "20.000 TL",
          ("ters yon", "ters istikamet", "ters yonde", "kontra", "ters seride gecti",
           "ters seritte ilerledi")),
    Ihlal("ters_yon_otoyol", "Otoyolda ters yön", "46/2-j-1",
          "Otoyollarda aracı ters istikamette sürmek",
          None, "90.000 TL ve 60 gün sürücü belgesine el koyma",
          ("otoyolda ters", "otobanda ters")),

    Ihlal("hatali_sollama", "Hatalı sollama", "54/1-a",
          "Öndeki aracı geçerken geçme kurallarına riayet etmemek", 20, "2.719 TL",
          ("hatali sollama", "sollama", "solladi", "sagdan sollama", "sagdan gecti",
           "sagdan gecis")),
    Ihlal("yasak_sollama", "Yasak yerde sollama", "54/1-b",
          "Geçmenin yasak olduğu yerlerde önündeki aracı geçmek", 20, "2.719 TL",
          ("yasak yerde sollama", "kesik olmayan", "duz cizgi", "devamli cizgi")),
    Ihlal("yol_vermeme", "Geçiş yapmak isteyene yol vermemek", "55/2-c",
          "54 üncü maddede yazılı durumlar dışında, geçiş yapmak isteyenlere yol "
          "vermemek, geçilmekte iken bir başka aracı geçmeye veya sola dönmeye kalkışmak",
          15, "1.000 TL",
          ("yol vermedi", "yol vermeme", "gecise izin vermedi")),

    Ihlal("cep_telefonu", "Seyir halinde cep telefonu kullanmak", "73/c",
          "Seyir halinde cep veya araç telefonu ya da benzer haberleşme cihazlarını "
          "ele alarak kullanmak", 10,
          "1. ihlalde 5.000 TL, bir yıl içindeki 3. ve sonraki ihlalde 20.000 TL",
          ("cep telefonu", "telefon", "telefonla", "elinde telefon", "mesajlasarak")),

    Ihlal("yaya_gecidi", "Yaya/okul geçidinde yayaya yol vermemek", "74/b",
          "Görevli bir kişi veya ışıklı trafik işareti bulunmayan ancak trafik işareti "
          "veya levhalarıyla belirlenmiş yaya veya okul geçitlerine yaklaşırken "
          "yavaşlamamak, varsa buralardan geçen veya geçmek üzere bulunan yayalara "
          "durarak ilk geçiş hakkını vermemek", 20, "5.662 TL",
          ("yaya gecidi", "okul gecidi", "yayaya yol vermedi", "yaya")),
    Ihlal("donusde_yaya", "Dönüşte yayaya ilk geçiş hakkı vermemek", "53/2-a",
          "Sağa ve sola dönüşlerde kurallara uygun olarak geçiş yapan yayalara ilk "
          "geçiş hakkını vermemek", 20, "1.246 TL",
          ("donusta yaya", "donerken yaya")),
    Ihlal("yaya_yolunda_arac", "Yaya yolunda/kaldırımda araç sürmek", "46/2-k",
          "Yaya yollarında araç sürmek", None, "5.000 TL",
          ("kaldirimda", "kaldirimdan", "yaya yolunda", "tretuvar")),

    Ihlal("kavsak_gecis_hakki", "Kavşakta geçiş hakkını vermemek", "57/1-a",
          "Kavşaklara yaklaşırken kavşaktaki şartlara uyacak şekilde yavaşlamamak, "
          "dikkatli olmamak, geçiş hakkı olan araçlara ilk geçiş hakkını vermemek",
          20, "5.000 TL",
          ("kavsakta gecis", "gecis hakki", "kavsakta yol vermedi", "kavsak")),
    Ihlal("kavsak_isgali", "Kavşağı kilitlemek", "57/1-d",
          "Işıklı trafik işaretleri izin verse bile trafik akımı kendisini kavşak "
          "içinde durmaya zorlayacak veya diğer doğrultudaki trafiğin geçişine engel "
          "olacak hallerde kavşağa girmek", 20, "1.000 TL",
          ("kavsagi kilitledi", "kavsak ortasinda", "kavsagi kapatti", "kavsak isgali")),

    Ihlal("saga_donus", "Sağa dönüş kuralı ihlali", "53/1-a",
          "Sağa dönüş kurallarına riayet etmemek", 20, "1.246 TL",
          ("saga donus", "saga donerken")),
    Ihlal("sola_donus", "Sola dönüş kuralı ihlali", "53/1-b",
          "Sola dönüş kurallarına riayet etmemek", 20, "1.246 TL",
          ("sola donus", "sola donerken")),
    Ihlal("sinyal_vermeme", "Sinyal vermeden manevra", "67/1-c",
          "Dönüşlerde veya şerit değiştirmelerde niyetini dönüş işaret ışıkları veya "
          "kol işareti ile açıkça ve yeterli şekilde belirtmemek, işaretlere manevra "
          "süresince devam etmemek ve biter bitmez sona erdirmemek", 20, "2.719 TL",
          ("sinyal", "sinyalsiz", "sinyal vermeden", "flasor vermeden")),
    Ihlal("geri_gitme", "Kurallara aykırı geri gitmek/dönmek", "67/1-b",
          "Yönetmelikte belirtilen şartlar dışında geriye dönmek veya geriye gitmek, "
          "izin verilen hallerde bu manevraları yaparken karayolunu kullananlar için "
          "tehlike veya engel yaratmak", 20, "2.719 TL",
          ("geri gitti", "geri geldi", "geri manevra", "u donusu", "u-donusu")),
    Ihlal("tehlikeli_manevra", "Tehlike doğuracak şekilde manevra", "67/1-a",
          "Karayolunun sağına veya soluna yanaşırken, sağa veya sola dönerken, "
          "karayolunu kullananlar için tehlike doğurabilecek ve bunların hareketlerini "
          "zorlaştıracak şekilde davranmak", 20, "2.719 TL",
          ("tehlikeli manevra", "ani manevra", "tehlikeye dusurdu")),

    Ihlal("trafigi_engelleme", "Keyfi hareketlerle trafiği engellemek", "46/2-n-1",
          "Aracı kol veya grup halinde ya da münferiden sürerken, diğer araçların "
          "geçişini zorlaştıracak veya tehlikeye sokacak şekilde keyfi hareketlerle "
          "trafiğin akışını kısmen veya tamamen engelleyecek şekilde karayolu üzerinde "
          "durdurmak",
          None, "90.000 TL ve 60 gün sürücü belgesine el koyma",
          ("trafigi engelledi", "yolu kapatti", "konvoy", "drift", "duman")),
    Ihlal("saldirgan_takip", "Trafikte saldırı amaçlı takip", "46/4",
          "Trafikte saldırı amacıyla başka bir aracı ısrarla takip etmek veya bu "
          "amaçla araçtan inmek",
          None, "60 gün sürücü belgesine el koyma",
          ("saldiri", "saldirgan", "israrla takip", "yol kesti", "tehdit")),

    Ihlal("duraklama_yasagi", "Duraklama yasağı ihlali", "60/1-a",
          "Taşıt yolu üzerinde duraklamanın yasaklandığının bir trafik işareti ile "
          "belirtilmiş olduğu yerlerde duraklamak", 10, "1.246 TL",
          ("duraklama", "durakladi"), "duraklama"),
    Ihlal("park_yasagi", "Park yasağı ihlali", "61/1-b",
          "Taşıt yolu üzerinde park etmenin trafik işaretleri ile yasaklandığı "
          "yerlerde park etmek", 10, "1.246 TL",
          ("park yasagi", "park etti", "hatali park", "park"), "park"),
    Ihlal("gecis_yolu_park", "Geçiş yolu önüne/üzerine park", "61/1-c",
          "Taşıt yolu üzerinde geçiş yolları önünde veya üzerinde park etmek",
          10, "1.246 TL",
          ("gecis yoluna park", "garaj onune", "apartman onune"), "park"),
    Ihlal("kaldirima_park", "Yaya yoluna/kaldırıma park", "61/1-n",
          "Yönetmelikte belirtilen haller dışında yaya yollarında park etmek",
          10, "1.246 TL",
          ("kaldirima park", "kaldirimda park", "yaya yoluna park", "yaya yolunda park",
           "kaldirim uzerine park"), "park"),
    Ihlal("engelli_park", "Engelli park yerine park", "61/1-o",
          "Taşıt yolu üzerinde engellilerin araçları için ayrılmış park yerlerinde "
          "park etmek", 10, "2.492 TL",
          ("engelli park", "engelli yerine", "engelli arac yeri"), "park"),
    Ihlal("yasak_yere_park", "Duraklamanın yasak olduğu yere park", "61/1-a",
          "Taşıt yolu üzerinde duraklamanın yasaklandığı yerlere park etmek",
          15, "1.246 TL",
          ("yaya gecidine park", "yaya gecidi uzerine park", "yaya gecidinde park",
           "gecide park", "kavsaga park", "kavsakta park", "donemece park",
           "tunele park", "rampaya park", "duraklama yasagi olan"), "park"),
    Ihlal("duraga_park", "Durak levhasına 15 m içinde park", "61/1-e",
          "Kamu hizmeti yapan yolcu taşıtlarının duraklarını belirten levhalara iki "
          "yönden onbeş metrelik mesafe içinde park etmek", 10, "1.246 TL",
          ("duraga park", "otobus duragina park", "taksi duragina park",
           "durak yerine park", "durakta park"), "park"),
    Ihlal("kopruye_park", "Alt/üst geçit veya köprü üzerine park", "61/1-k",
          "Taşıt yolu üzerinde park için yer ayrılmamış veya trafik işaretleri ile "
          "belirtilmemiş alt geçit, üst geçit ve köprüler üzerinde veya bunlara on "
          "metrelik mesafe içinde park etmek", 15, "1.246 TL",
          ("kopruye park", "koprude park", "ust gecide park", "alt gecide park"), "park"),
    Ihlal("cikisi_engelleyen_park", "Park etmiş aracın çıkışını engelleyen park", "61/1-g",
          "Taşıt yolu üzerinde kurallara uygun şekilde park etmiş araçların çıkmasına "
          "engel olacak yerlerde park etmek", 10, "1.246 TL",
          ("cikisini engelledi", "onunu kapatti", "cift park", "ciftli park",
           "aracin onune park"), "park"),

    Ihlal("gecitte_duraklama", "Yaya/okul geçidinde duraklamak", "60/1-c",
          "Taşıt yolu üzerinde yaya ve okul geçitleri ile diğer geçitlerde duraklamak",
          10, "1.246 TL",
          ("yaya gecidinde durakladi", "gecitte durakladi", "gecit uzerinde durakladi"),
          "duraklama"),
    Ihlal("kavsakta_duraklama", "Kavşak/tünel/köprüde duraklamak", "60/1-d",
          "Taşıt yolu üzerinde kavşaklar, tüneller, rampalar, köprüler ve bağlantı "
          "yollarında veya buralara yerleşim birimleri içinde beş metre veya yerleşim "
          "birimleri dışında yüz metre mesafede duraklamak", 10, "1.246 TL",
          ("kavsakta durakladi", "koprude durakladi", "tunelde durakladi",
           "rampada durakladi"), "duraklama"),
    Ihlal("durakta_duraklama", "Otobüs/tramvay/taksi durağında duraklamak", "60/1-f",
          "Taşıt yolu üzerinde otobüs, tramvay ve taksi duraklarında duraklamak",
          10, "1.246 TL",
          ("durakta durakladi", "otobus duraginda", "taksi duraginda"), "duraklama"),
    Ihlal("sol_seritte_duraklama", "Sol şeritte duraklamak", "60/1-b",
          "Taşıt yolu üzerinde sol şeritte (raylı sistemin bulunduğu yollar hariç) "
          "duraklamak", 10, "1.246 TL",
          ("sol seritte durakladi", "sol seritte durdu"), "duraklama"),

    Ihlal("hiz_ihlali", "Hız sınırı ihlali", "51/2",
          "Belirlenen hız sınırını aşmak (aşım miktarına göre 51/2-a veya 51/2-b "
          "bentleri uygulanır)", None,
          "aşım oranına göre 1.246 TL ile 25.000 TL arasında",
          ("hiz siniri", "hiz ihlali", "asiri hiz", "hizli", "surat")),
    Ihlal("emniyet_kemeri", "Emniyet kemeri takmamak", "78/1-a",
          "Bulundurulma zorunluluğu olan araçlarda emniyet kemerini usulüne uygun "
          "olarak kullanmamak", 15, "2.500 TL",
          ("emniyet kemeri", "kemer takmadan", "kemersiz")),
    Ihlal("isik_donanimi", "Işık donanımı eksik/bozuk veya kurallara aykırı", "30/1-a",
          "Servis freni, lastikleri, dış ışık donanımından yakını ve uzağı gösteren "
          "ışıklar ile park, fren ve dönüş ışıkları noksan, bozuk veya teknik şartlara "
          "aykırı olan araçları kullanmak", 20, "1.246 TL",
          ("stop lambasi", "far bozuk", "isik donanimi", "uzun far", "lamba yanmiyor")),
    Ihlal("abarti_aksesuar", "Tehlikeli süs/aksesuar/çıkıntı", "30/1-b",
          "Kaza halinde içindekiler için tehlikeli olabilecek süs, aksesuar, eşya ve "
          "çıkıntıları olan, karayolunu kullananlar için tehlike yaratan araçları "
          "kullanmak", 20, "2.719 TL",
          ("abarti egzoz", "egzoz", "aksesuar", "cikinti")),
    Ihlal("plaka_ihlali", "Plaka/ayırım işareti eksikliği", "26/1",
          "Araçlarda bulundurulması mecburi olan (çalışma yerini ve şeklini, kapasite "
          "ile diğer niteliklerini belirleyen plaka, ışık, renk, şekil, sembol ve yazı "
          "gibi) ayırım işaretlerini bulundurmamak", 5, "1.246 TL",
          ("plakasiz", "plaka kapali", "plaka okunmuyor", "plaka egik", "plaka yok")),
)


_TR_KARSILIK = str.maketrans({
    "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g", "ı": "i", "I": "i", "İ": "i",
    "ö": "o", "Ö": "o", "ş": "s", "Ş": "s", "ü": "u", "Ü": "u", "â": "a", "î": "i",
})


def normalize(metin: str) -> str:
    """Türkçe karakterleri ve noktalamayı sadeleştirip eşleştirmeye hazırlar.

    Kullanıcı 'kırmızı ışık' da yazabiliyor 'kirmizi isik' da; ikisi de aynı
    anahtara düşsün diye iki taraf da ASCII'ye katlanıyor."""
    if not metin:
        return ""
    sade = metin.translate(_TR_KARSILIK).lower()
    sade = re.sub(r"[^a-z0-9]+", " ", sade)
    return f" {sade.strip()} "


# Metinde bunlardan biri geçiyorsa araç duruyor demektir. Bu bir filtre DEĞİL,
# sıralama ölçütü: "yaya geçidine park" ifadesinde "yaya gecidi" anahtarı
# "park"tan uzun olduğu için en-uzun-kelime kuralı 74/b'yi (seyir halinde
# yayaya yol vermemek) öne çıkarıyordu. Artık park/duraklama bentleri başa
# alınıyor ama sürüş maddeleri de listede kalıyor - kullanıcı doğrusunu seçiyor,
# eleme kararını kod vermiyor.
DURAN_ARAC_BELIRTECLERI = ("park", "parket", "parkl", "durakla", "duraklat", "birakmis")

DURAN_GRUPLAR = ("park", "duraklama")


def _duruyor_mu(hedef: str) -> bool:
    """Normalize edilmiş metin duran bir aracı mı anlatıyor?"""
    return any(kelime.startswith(belirtec)
               for kelime in hedef.split()
               for belirtec in DURAN_ARAC_BELIRTECLERI)


def adaylari_bul(metin: str, limit: int = 8) -> list:
    """Metne uyan tüm maddeleri, en olası olan başta olmak üzere döndürür.

    Sıralama (uyum, anahtar_uzunlugu) ikilisine göre: önce duran/hareketli
    araç uyumu, sonra eşleşen anahtar kelimenin uzunluğu. Tek bir madde
    dayatmak yerine aday listesi vermek, yanlış bendi resmi bir ihbara
    yazma riskini kullanıcının gözüne taşıyor."""
    hedef = normalize(metin)
    if not hedef.strip():
        return []
    duruyor = _duruyor_mu(hedef)
    puanlar = {}
    for ihlal in KATALOG:
        en_uzun = 0
        for kelime in ihlal.kelimeler:
            anahtar = normalize(kelime).strip()
            if anahtar and anahtar in hedef:
                en_uzun = max(en_uzun, len(anahtar))
        if not en_uzun:
            continue
        uyum = 1 if duruyor == (ihlal.grup in DURAN_GRUPLAR) else 0
        puanlar[ihlal] = (uyum, en_uzun)
    sirali = sorted(puanlar, key=lambda i: puanlar[i], reverse=True)
    return sirali[:limit]


def eslestir(metin: str):
    """En olası tek maddeyi döndürür (aday listesinin ilk sırası), yoksa None."""
    adaylar = adaylari_bul(metin, limit=1)
    return adaylar[0] if adaylar else None


def anahtardan_bul(anahtar: str):
    """Katalog anahtarı ya da GUI etiketiyle kayıt getirir."""
    for ihlal in KATALOG:
        if anahtar in (ihlal.anahtar, ihlal.etiket):
            return ihlal
    return None


def etiketler() -> list:
    """GUI açılır listesi / CLI numaralı listesi için görünen adlar."""
    return [ihlal.etiket for ihlal in KATALOG]


def dayanak_metni(ihlaller) -> str:
    """Bir veya birden çok ihlal için tek satırlık kanuni dayanak metni.

    Tek ihlalde madde doğrudan cümleye giriyor; birden fazlasında kanun adı
    bir kez yazılıp maddeler numaralanıyor, çünkü site açıklamayı tek satıra
    indirip büyük harfe çeviriyor - tekrar eden kanun adı metni okunmaz hale
    getiriyordu."""
    ihlaller = [i for i in ihlaller if i is not None]
    if not ihlaller:
        return ""
    if len(ihlaller) == 1:
        return ihlaller[0].dayanak_metni()
    parcalar = []
    for sira, ihlal in enumerate(ihlaller, 1):
        parca = f"{sira}) Madde {ihlal.madde} - {ihlal.resmi_tanim}"
        if ihlal.ceza_puani:
            parca += f" ({ihlal.ceza_puani} ceza puanı)"
        parcalar.append(parca + ".")
    return f"Kanuni dayanak: {KANUN_ADI}. " + " ".join(parcalar)


def dayanak_ekle(aciklama: str, ihlaller=None) -> tuple:
    """Açıklamanın sonuna kanuni dayanağı ekler; (yeni_metin, ihlal_listesi) döner.

    ihlaller tek bir Ihlal de olabilir, liste de. Hiç verilmezse açıklamadan
    otomatik eşleştirilir (tek madde). Eşleşme yoksa metin olduğu gibi kalır -
    uydurma madde yazmaktansa hiç yazmamak doğrusu."""
    if ihlaller is None:
        ihlaller = [eslestir(aciklama)]
    elif isinstance(ihlaller, Ihlal):
        ihlaller = [ihlaller]
    ihlaller = [i for i in ihlaller if i is not None]
    if not ihlaller:
        return aciklama, []
    dayanak = dayanak_metni(ihlaller)
    if dayanak in aciklama:
        return aciklama, ihlaller
    return f"{aciklama}\n{dayanak}", ihlaller
