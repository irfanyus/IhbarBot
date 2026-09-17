import json
import math
import time
import urllib.parse
import urllib.request

from geopy.geocoders import Nominatim
from geopy.exc import GeopyError

# Nominatim, koordinat OSM'de ismi girilmemiş bir yol parçasına düşerse
# adreste hiç 'road' döndürmüyor (örn. Tuzla Demokrasi Caddesi'nin bir bölümü:
# way/187213433 sadece highway=trunk, name yok). Bu durumda çevredeki isimli
# yolları Overpass'tan çekip en yakınını sokak olarak kullanıyoruz.
# Ana Overpass sunucusu yoğun saatlerde zaman aşımına uğruyor; sırayla yedeklere düşüyoruz.
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
OVERPASS_RADIUS_M = 250
OVERPASS_TIMEOUT_SEC = 20
# Sunucu başına HTTP bekleme sınırı. Üç sunucu da düşükken eskiden her adres
# sorgusu 3 x 20 sn = 1 dakika takılıyordu.
OVERPASS_HTTP_TIMEOUT_SEC = 12
# Bütün sunucular yanıt vermeyince bu kadar süre Overpass hiç denenmez; yoksa
# bir kesinti, arkası arkasına gelen her sorguda aynı bekleyişi tekrarlatıyor.
OVERPASS_ARA_SN = 300
_overpass_kapali_bitis = 0.0

NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
# Nominatim kullanım kuralı: saniyede en fazla bir istek. reverse_geocode()
# hemen öncesinde geopy üzerinden zaten bir istek atmış oluyor.
NOMINATIM_ARA_SN = 1.1
# zoom 12-13 noktayı İÇİNE ALAN idari sınırı (mahalle) döndürüyor; 14 ve üstü
# yeniden semt noktasına ya da yola iniyor.
MAHALLE_ZOOMLARI = (13, 12)

# Otoyol/bağlantı yolu isimleri ihbar formundaki cadde-sokak listesinde çıkmadığı
# için, isimli bir cadde/sokak varsa onu tercih ediyoruz.
DEPRIORITIZED_HIGHWAYS = ("motorway", "motorway_link", "trunk_link", "primary_link", "secondary_link")


def _haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _overpass(query: str):
    """Overpass sorgusunu sırayla yedek sunuculara dener; hepsi düşerse None döner."""
    global _overpass_kapali_bitis
    if time.time() < _overpass_kapali_bitis:
        return None
    for url in OVERPASS_URLS:
        try:
            req = urllib.request.Request(
                url,
                data=urllib.parse.urlencode({"data": query}).encode("utf-8"),
                headers={"User-Agent": "TrafikIhbarBot_1.0"},
            )
            with urllib.request.urlopen(req, timeout=OVERPASS_HTTP_TIMEOUT_SEC) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[UYARI] Overpass sorgusu başarısız ({url}): {e}")
    _overpass_kapali_bitis = time.time() + OVERPASS_ARA_SN
    print(f"[UYARI] Overpass sunucularının hiçbiri yanıt vermedi; "
          f"{OVERPASS_ARA_SN // 60} dakika boyunca denenmeyecek.")
    return None


def _mahalle_adi_mi(name: str) -> bool:
    # Türkiye'de OSM mahalle sınırları "X Mahallesi" diye adlandırılıyor;
    # ilçe/il sınırlarını bu ekten ayırt ediyoruz. Karşılaştırma casefold ile:
    # str.upper() Türkçe bilmiyor, "Mahallesi" -> "MAHALLESI" (noktasız I) yapıp
    # "MAHALLESİ" ile eşleşmiyor.
    return name.casefold().endswith("mahallesi")


def _nominatim_mahalle(latitude: float, longitude: float):
    """Nominatim'in düşük zoom'lu ters sorgusuyla noktayı içine alan mahalle sınırı."""
    for zoom in MAHALLE_ZOOMLARI:
        time.sleep(NOMINATIM_ARA_SN)
        url = NOMINATIM_REVERSE_URL + "?" + urllib.parse.urlencode({
            "format": "jsonv2", "lat": latitude, "lon": longitude,
            "zoom": zoom, "addressdetails": 0,
        })
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "TrafikIhbarBot_1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                sonuc = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"[UYARI] Nominatim mahalle sorgusu başarısız (zoom {zoom}): {e}")
            return None
        name = (sonuc.get("name") or "").strip()
        # Sınırın kendisi olmalı: aynı zoom'da bazen semt noktası da dönebiliyor.
        if sonuc.get("category") == "boundary" and _mahalle_adi_mi(name):
            return name
    return None


def official_mahalle(latitude: float, longitude: float):
    """
    Noktanın içinde kaldığı resmî mahalleyi OSM idari sınırlarından okur.

    Neden gerekli: Nominatim'in `suburb`/`quarter` alanları resmî mahalle değil,
    semt adı döndürebiliyor. 40.964543,29.103548 için `suburb` "Kozyatağı
    Mahallesi" diyor ama nokta gerçekte Bostancı Mahallesi sınırları içinde;
    ihbar formunun cadde/sokak listesi mahalleye göre süzüldüğü için yanlış
    mahalle seçilince aranan sokak listede hiç çıkmıyor (10.09.2026).

    Asıl kaynak Nominatim'in zoom 13'teki ters sorgusu: en yakın nesneyi değil,
    noktayı içine alan sınırı döndürüyor ve Overpass `is_in` ile aynı cevabı
    1 saniyenin altında veriyor. 14.09.2026'ya kadar yalnızca Overpass
    kullanılıyordu; o gün üç Overpass sunucusu da 504/zaman aşımı verirken her
    adres sorgusu yaklaşık bir dakika takılıp sessizce yanlışa açık Nominatim
    alanlarına düşüyordu. Overpass artık yalnızca yedek.
    """
    ad = _nominatim_mahalle(latitude, longitude)
    if ad:
        return ad

    data = _overpass(f"[out:json][timeout:{OVERPASS_TIMEOUT_SEC}];"
                     f"is_in({latitude},{longitude})->.a;"
                     f'area.a["boundary"="administrative"]["name"];'
                     f"out tags;")
    if data is None:
        return None

    adaylar = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        name = (tags.get("name") or "").strip()
        if not _mahalle_adi_mi(name):
            continue
        try:
            level = int(tags.get("admin_level", 0))
        except (TypeError, ValueError):
            level = 0
        adaylar.append((level, name))

    if not adaylar:
        return None
    # Birden fazla eşleşirse en küçük alan (en yüksek admin_level) doğru olan.
    return max(adaylar)[1]


def nearest_named_road(latitude: float, longitude: float, radius_m: int = OVERPASS_RADIUS_M):
    """
    Overpass API ile verilen noktanın çevresindeki isimli yolları arar ve en yakınının
    adını döndürür. Ağ hatası / sonuç yoksa None döner (çağıran taraf 'Bilinmiyor' der).
    """
    query = (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_SEC}];"
        f'way(around:{radius_m},{latitude},{longitude})["highway"]["name"];'
        f"out tags geom;"
    )
    data = _overpass(query)

    if data is None:
        print("[UYARI] Hiçbir Overpass sunucusuna ulaşılamadı; sokak elle girilmeli.")
        return None

    candidates = []
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue
        # Yolun geometrisindeki en yakın düğüme olan mesafe — parça merkezinden daha doğru.
        distances = [
            _haversine_m(latitude, longitude, node["lat"], node["lon"])
            for node in element.get("geometry", [])
            if "lat" in node and "lon" in node
        ]
        if not distances:
            continue
        deprioritized = tags.get("highway") in DEPRIORITIZED_HIGHWAYS
        candidates.append((deprioritized, min(distances), name))

    if not candidates:
        return None

    deprioritized, distance, name = min(candidates)
    print(f"[INFO] Koordinatın düştüğü yol OSM'de isimsiz; en yakın isimli yol kullanıldı: "
          f"{name} (~{distance:.0f} m)")
    return name


def reverse_geocode(latitude: float, longitude: float) -> dict:
    """
    Reverse geocoding using Nominatim service.
    
    Parameters:
    latitude (float): Latitude of the location.
    longitude (float): Longitude of the location.
    
    Returns:
    dict: Map containing keys 'il', 'ilçe', 'mahalle', and 'sokak'.
          Values default to 'Bilinmiyor' if not found.
    """
    geolocator = Nominatim(user_agent="TrafikIhbarBot_1.0")

    # Sınır durumlarında yedek mahalle adayı olarak kullanılıyor (aşağıya bakın).
    quarter = None

    result = {
        'il': 'Bilinmiyor',
        'ilçe': 'Bilinmiyor',
        'mahalle': 'Bilinmiyor',
        'sokak': 'Bilinmiyor'
    }
    
    try:
        # Querying location with coordinates
        location = geolocator.reverse((latitude, longitude), exactly_one=True, timeout=10)
        
        if location and location.raw and 'address' in location.raw:
            address = location.raw['address']
            
            # 1. 'il' Mapping (State / Province)
            result['il'] = address.get('province') or address.get('state') or 'Bilinmiyor'
            
            # 2. 'ilçe' Mapping (Town / County / District / City District / City)
            result['ilçe'] = (
                address.get('town') or 
                address.get('county') or 
                address.get('district') or 
                address.get('city_district') or 
                address.get('city') or 
                'Bilinmiyor'
            )
            
            # 3. 'mahalle' Mapping (Neighbourhood / Suburb / Village / Quarter)
            # Not: Bu alanlar semt adı da döndürebiliyor; asıl kaynak aşağıdaki
            # official_mahalle(), burası yalnızca yedek.
            result['mahalle'] = (
                address.get('neighbourhood') or 
                address.get('suburb') or 
                address.get('village') or 
                address.get('quarter') or 
                'Bilinmiyor'
            )
            
            # 4. 'sokak' Mapping (Road / Street / Pedestrian path)
            result['sokak'] = address.get('road') or address.get('street') or 'Bilinmiyor'

            quarter = address.get('quarter')
            
    except GeopyError as e:
        print(f"[ERROR] Geopy connection/service error: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error during reverse geocoding: {e}")

    # Mahalleyi idari sınırdan doğrula: ihbar formu cadde/sokak listesini mahalleye
    # göre süzdüğü için yanlış mahalle, doğru sokağın listede hiç çıkmaması demek.
    nominatim_mahalle = result['mahalle']
    resmi = official_mahalle(latitude, longitude)
    if resmi and resmi != nominatim_mahalle:
        print(f"[INFO] Mahalle idari sınıra göre düzeltildi: "
              f"{nominatim_mahalle} -> {resmi}")
        result['mahalle'] = resmi

    # Sınıra yakın noktalarda tek bir doğru cevap olmayabiliyor: sokak iki
    # mahallenin sınırında uzanıyorsa Nominatim birini, idari sınır diğerini
    # söylüyor. Hangisinin doğru olduğunu ancak sitenin kendi listesi biliyor,
    # bu yüzden adayları sırayla veriyoruz — form_filler ilkinde sokağı
    # bulamazsa diğerini deniyor.
    adaylar = []
    for aday in (result['mahalle'], nominatim_mahalle, quarter):
        if aday and aday != 'Bilinmiyor' and aday not in adaylar:
            adaylar.append(aday)
    result['mahalle_adaylari'] = adaylar

    # Nominatim isimsiz bir yol parçasına düştüyse sokak boş kalıyor — çevredeki
    # en yakın isimli yolu Overpass'tan çekip dolduruyoruz.
    if result['sokak'] == 'Bilinmiyor':
        fallback = nearest_named_road(latitude, longitude)
        if fallback:
            result['sokak'] = fallback

    return result
