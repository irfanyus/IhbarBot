from geopy.geocoders import Nominatim
from geopy.exc import GeopyError

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
            result['mahalle'] = (
                address.get('neighbourhood') or 
                address.get('suburb') or 
                address.get('village') or 
                address.get('quarter') or 
                'Bilinmiyor'
            )
            
            # 4. 'sokak' Mapping (Road / Street / Pedestrian path)
            result['sokak'] = address.get('road') or address.get('street') or 'Bilinmiyor'
            
    except GeopyError as e:
        print(f"[ERROR] Geopy connection/service error: {e}")
    except Exception as e:
        print(f"[ERROR] Unexpected error during reverse geocoding: {e}")
        
    return result
