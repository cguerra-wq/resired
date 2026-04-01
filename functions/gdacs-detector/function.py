# ResiRed - fn-gdacs-detector
# Mercy Corps Colombia - San Andres y Providencia
# Basado en AAAStorms (mc-t4d) - CC BY-NC 4.0
# Adaptado para ciclones tropicales Atlantico + deteccion San Andres

import math
import feedparser
import requests
import pandas as pd
from parse_storms import get_cyclones, get_advisories, get_wind_forecasts

# Coordenadas de referencia
SAN_ANDRES_LAT  = 12.5000
SAN_ANDRES_LON  = -81.7000
PROVIDENCIA_LAT = 13.3470
PROVIDENCIA_LON = -81.3720

# Solo Atlantico para el piloto (AL)
# EP = Pacifico Este, fuera del alcance de San Andres
RSS_URLS = [
    "https://www.nhc.noaa.gov/gis-at.xml",  # Atlantico - critico
]

RADIO_MONITOREO_KM = 500


def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos geograficos."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def saffir_simpson(velocidad_kt):
    """Categoria segun velocidad en nudos."""
    if velocidad_kt < 34:  return 0   # Depresion o TS
    elif velocidad_kt < 64: return 0  # Tormenta tropical
    elif velocidad_kt < 83: return 1
    elif velocidad_kt < 96: return 2
    elif velocidad_kt < 113: return 3
    elif velocidad_kt < 137: return 4
    else:                    return 5


def get_gdacs_level():
    """
    Consulta GDACS para ciclones tropicales activos.
    Retorna el nivel de alerta si hay algo cerca de San Andres.
    """
    try:
        feed = feedparser.parse('https://www.gdacs.org/xml/rss.xml')
        for entry in feed.entries:
            # GDACS marca ciclones con eventtype TC
            if hasattr(entry, 'gdacs_eventtype') and entry.gdacs_eventtype == 'TC':
                lat = float(getattr(entry, 'geo_lat', 0))
                lon = float(getattr(entry, 'geo_long', 0))
                dist = haversine_km(SAN_ANDRES_LAT, SAN_ANDRES_LON, lat, lon)
                if dist < RADIO_MONITOREO_KM:
                    return {
                        'nivel': getattr(entry, 'gdacs_alertlevel', 'Green'),
                        'nombre': getattr(entry, 'gdacs_eventname', 'UNKNOWN'),
                        'distancia_km': round(dist, 1)
                    }
    except Exception as e:
        print(f'GDACS no disponible: {e}')
    return None


def detectar_ciclones():
    """
    Funcion principal. Lee NHC + GDACS y retorna
    los ciclones que estan dentro del radio de monitoreo.
    """
    resultados = []

    for url in RSS_URLS:
        print(f'Consultando NHC: {url}')
        feed = feedparser.parse(url)

        if feed.bozo:
            print(f'Error en feed: {url}')
            continue

        # Sin tormentas activas
        if len(feed.entries) == 0:
            print('Sin entradas en el feed.')
            continue

        primera = feed.entries[0].title
        if 'no tropical cyclones' in primera.lower():
            print(f'Sin ciclones activos: "{primera}"')
            continue

        # Hay ciclones - procesarlos con el codigo de AAAStorms
        storms = get_cyclones(feed)
        storms = get_advisories(storms)
        storms = get_wind_forecasts(storms)

        for s in storms:
            # Obtener posicion del ciclon
            lat = float(getattr(s, 'nhc_lat', 0) or 0)
            lon = float(getattr(s, 'nhc_lon', 0) or 0)

            if lat == 0 and lon == 0:
                # Si no hay coordenadas directas, igual incluimos
                # la geo-interseccion lo filtrara en el siguiente step
                dist = 999
            else:
                dist_sa = haversine_km(SAN_ANDRES_LAT, SAN_ANDRES_LON, lat, lon)
                dist_pr = haversine_km(PROVIDENCIA_LAT, PROVIDENCIA_LON, lat, lon)
                dist = min(dist_sa, dist_pr)

            if dist <= RADIO_MONITOREO_KM:
                velocidad_kt = 0
                try:
                    # nhc_wind viene como "65 mph" - convertir a kt
                    viento_str = s.get('nhc_wind', '0 mph')
                    mph = float(viento_str.split()[0])
                    velocidad_kt = mph / 1.15078
                except:
                    pass

                resultado = {
                    'nombre':        s.get('nhc_name', 'UNKNOWN'),
                    'id_noaa':       s.get('nhc_atcf', ''),
                    'tipo':          s.get('nhc_type', ''),
                    'velocidad_kt':  round(velocidad_kt, 1),
                    'velocidad_mph': s.get('nhc_wind', ''),
                    'categoria':     saffir_simpson(velocidad_kt),
                    'distancia_km':  round(dist, 1),
                    'lat':           lat,
                    'lon':           lon,
                    'wind_shapefiles': s.get('windforecast_noaa', {}),
                    'resumen_url':   s.get('summary', ''),
                }
                resultados.append(resultado)
                print(f'Ciclon detectado: {resultado["nombre"]} '
                      f'Cat {resultado["categoria"]} '
                      f'a {resultado["distancia_km"]} km')

    # Consultar GDACS en paralelo
    gdacs = get_gdacs_level()
    if gdacs:
        print(f'GDACS alerta: {gdacs["nivel"]} - {gdacs["nombre"]} '
              f'a {gdacs["distancia_km"]} km')

    if not resultados and not gdacs:
        print('Sin ciclones en el radio de monitoreo. Sistema OK.')

    return {
        'ciclones_nhc': resultados,
        'gdacs':        gdacs,
        'timestamp':    str(pd.Timestamp.now(tz='UTC'))
    }


# --- Punto de entrada para prueba local ---
if __name__ == '__main__':
    resultado = detectar_ciclones()
    import json
    print(json.dumps(resultado, indent=2, default=str))