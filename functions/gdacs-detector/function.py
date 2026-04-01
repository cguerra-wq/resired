# ResiRed - fn-gdacs-detector
# Mercy Corps Colombia - San Andres y Providencia
# Basado en AAAStorms (mc-t4d) - CC BY-NC 4.0
# Fuentes: NOAA NHC + GDACS + ECMWF (Open-Meteo) + NOAA CO-OPS

import math
import json
import feedparser
import requests
import pandas as pd
from parse_storms import get_cyclones, get_advisories, get_wind_forecasts

# ─── Coordenadas de referencia ────────────────────────────────────────────────
SAN_ANDRES_LAT  = 12.5000
SAN_ANDRES_LON  = -81.7000
PROVIDENCIA_LAT = 13.3470
PROVIDENCIA_LON = -81.3720

# Radio de monitoreo: suficiente para 48-72h de antelacion
RADIO_MONITOREO_KM = 500

# Solo Atlantico (AL) - San Andres esta en el Mar Caribe
RSS_URLS = [
    "https://www.nhc.noaa.gov/gis-at.xml",
]

# NOAA CO-OPS: estacion mas cercana a San Andres
# 8768094 = Lake Charles, LA (referencia Caribe occidental)
# Usamos la estacion de San Juan PR como proxy del Caribe
COOPS_STATION_ID = "9755371"  # San Juan, Puerto Rico
COOPS_URL = (
    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
    "?station={station}&product=water_level&datum=MLLW"
    "&time_zone=gmt&units=metric&format=json&range=1"
)

# ECMWF via Open-Meteo - grilla 9km, sin API key
OPENMETEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude={lat}&longitude={lon}"
    "&hourly=windspeed_10m,windgusts_10m,precipitation"
    "&windspeed_unit=ms&forecast_days=3"
)


# ─── Utilidades ───────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos puntos geograficos."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def saffir_simpson(velocidad_kt):
    """Categoria Saffir-Simpson segun velocidad en nudos."""
    if velocidad_kt < 64:  return 0   # Depresion tropical o TS
    elif velocidad_kt < 83: return 1
    elif velocidad_kt < 96: return 2
    elif velocidad_kt < 113: return 3
    elif velocidad_kt < 137: return 4
    else:                    return 5


def nivel_alerta(categoria, distancia_km):
    """
    Nivel de alerta para ResiRed basado en categoria y distancia.
    Retorna: 'rojo', 'naranja', 'amarillo', 'verde'
    """
    if categoria >= 3 and distancia_km < 300:
        return 'rojo'
    elif categoria >= 2 and distancia_km < 400:
        return 'naranja'
    elif categoria >= 1 and distancia_km < 500:
        return 'amarillo'
    else:
        return 'verde'


# ─── Fuente 1: NOAA NHC ───────────────────────────────────────────────────────

def consultar_nhc():
    """
    Fuente primaria. Lee el feed GIS del NHC Atlantico.
    Retorna lista de ciclones dentro del radio de monitoreo.
    Basado en AAAStorms (mc-t4d) - parse_storms.py
    """
    resultados = []

    for url in RSS_URLS:
        print(f'[NHC] Consultando: {url}')
        feed = feedparser.parse(url)

        if feed.bozo:
            print(f'[NHC] Error en el feed RSS')
            continue

        if not feed.entries:
            print('[NHC] Feed vacio')
            continue

        primera = feed.entries[0].title
        if 'no tropical cyclones' in primera.lower():
            print(f'[NHC] Sin ciclones activos. Fuera de temporada o mar tranquilo.')
            continue

        # Hay ciclones - procesar con codigo de AAAStorms
        storms = get_cyclones(feed)
        storms = get_advisories(storms)
        storms = get_wind_forecasts(storms)

        for s in storms:
            # Intentar obtener posicion
            try:
                lat = float(s.get('nhc_lat', 0) or 0)
                lon = float(s.get('nhc_lon', 0) or 0)
            except (ValueError, TypeError):
                lat, lon = 0.0, 0.0

            if lat == 0 and lon == 0:
                dist = 999  # sin coordenadas, igual incluir para geo-intersection
            else:
                dist_sa = haversine_km(SAN_ANDRES_LAT, SAN_ANDRES_LON, lat, lon)
                dist_pr = haversine_km(PROVIDENCIA_LAT, PROVIDENCIA_LON, lat, lon)
                dist = min(dist_sa, dist_pr)

            if dist > RADIO_MONITOREO_KM and dist != 999:
                print(f'[NHC] {s.get("nhc_name","?")} a {dist:.0f} km - fuera del radio')
                continue

            # Convertir velocidad mph → kt
            try:
                mph = float(str(s.get('nhc_wind', '0')).split()[0])
                velocidad_kt = mph / 1.15078
            except (ValueError, IndexError):
                velocidad_kt = 0.0

            cat = saffir_simpson(velocidad_kt)
            alerta = nivel_alerta(cat, dist)

            resultado = {
                'fuente':          'NHC',
                'nombre':          s.get('nhc_name', 'DESCONOCIDO'),
                'id_noaa':         s.get('nhc_atcf', ''),
                'tipo':            s.get('nhc_type', ''),
                'velocidad_kt':    round(velocidad_kt, 1),
                'velocidad_mph':   s.get('nhc_wind', ''),
                'categoria':       cat,
                'nivel_alerta':    alerta,
                'distancia_km':    round(dist, 1),
                'lat':             lat,
                'lon':             lon,
                'wind_forecast':   s.get('windforecast_noaa', {}),
                'resumen_url':     s.get('summary', ''),
            }
            resultados.append(resultado)
            print(f'[NHC] *** CICLON DETECTADO: {resultado["nombre"]} '
                  f'Cat {cat} | {alerta.upper()} | {dist:.0f} km ***')

    return resultados


# ─── Fuente 2: GDACS ──────────────────────────────────────────────────────────

def consultar_gdacs():
    """
    Fuente de verificacion. GDACS (ONU+UE) provee semaforo Verde/Naranja/Rojo
    y datos adicionales de impacto humanitario.
    """
    print('[GDACS] Consultando feed RSS...')
    try:
        feed = feedparser.parse('https://www.gdacs.org/xml/rss.xml')
        alertas = []

        for entry in feed.entries:
            tipo = getattr(entry, 'gdacs_eventtype', '')
            if tipo != 'TC':  # TC = Tropical Cyclone
                continue

            try:
                lat = float(getattr(entry, 'geo_lat', 0))
                lon = float(getattr(entry, 'geo_long', 0))
            except (ValueError, TypeError):
                continue

            dist_sa = haversine_km(SAN_ANDRES_LAT, SAN_ANDRES_LON, lat, lon)
            dist_pr = haversine_km(PROVIDENCIA_LAT, PROVIDENCIA_LON, lat, lon)
            dist = min(dist_sa, dist_pr)

            if dist <= RADIO_MONITOREO_KM:
                nivel = getattr(entry, 'gdacs_alertlevel', 'Green')
                alerta = {
                    'fuente':        'GDACS',
                    'nombre':        getattr(entry, 'gdacs_eventname', 'DESCONOCIDO'),
                    'nivel_gdacs':   nivel,  # Green / Orange / Red
                    'distancia_km':  round(dist, 1),
                    'lat':           lat,
                    'lon':           lon,
                    'severidad':     getattr(entry, 'gdacs_severity', ''),
                    'poblacion':     getattr(entry, 'gdacs_population', ''),
                    'url':           getattr(entry, 'link', ''),
                }
                alertas.append(alerta)
                print(f'[GDACS] *** ALERTA {nivel.upper()}: {alerta["nombre"]} '
                      f'a {dist:.0f} km ***')

        if not alertas:
            print('[GDACS] Sin ciclones en el radio de monitoreo')
        return alertas

    except Exception as e:
        print(f'[GDACS] No disponible: {e}')
        return []


# ─── Fuente 3: ECMWF via Open-Meteo ──────────────────────────────────────────

def consultar_ecmwf():
    """
    Modelo europeo de 9km via Open-Meteo. Sin API key.
    Provee pronostico de viento y precipitacion a 72h para San Andres.
    Util para detectar condiciones deterioradas antes de que el NHC confirme.
    """
    print('[ECMWF] Consultando Open-Meteo...')
    resultados = {}

    for nombre, lat, lon in [
        ('san_andres', SAN_ANDRES_LAT, SAN_ANDRES_LON),
        ('providencia', PROVIDENCIA_LAT, PROVIDENCIA_LON),
    ]:
        try:
            url = OPENMETEO_URL.format(lat=lat, lon=lon)
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()

            hourly = data.get('hourly', {})
            tiempos     = hourly.get('time', [])
            vientos     = hourly.get('windspeed_10m', [])
            rachas      = hourly.get('windgusts_10m', [])
            lluvia      = hourly.get('precipitation', [])

            # Maximos en las proximas 72 horas
            max_viento  = max((v for v in vientos if v is not None), default=0)
            max_racha   = max((r for r in rachas if r is not None), default=0)
            max_lluvia  = max((p for p in lluvia if p is not None), default=0)

            # Convertir m/s → kt para comparar con NHC
            max_viento_kt = round(max_viento * 1.94384, 1)
            max_racha_kt  = round(max_racha  * 1.94384, 1)

            # Alerta si viento supera umbral de tormenta tropical (34 kt)
            alerta_viento = max_viento_kt >= 34

            resultados[nombre] = {
                'fuente':          'ECMWF/Open-Meteo',
                'max_viento_ms':   round(max_viento, 1),
                'max_viento_kt':   max_viento_kt,
                'max_racha_kt':    max_racha_kt,
                'max_lluvia_mm':   round(max_lluvia, 1),
                'alerta_viento':   alerta_viento,
                'horizonte_horas': 72,
            }

            estado = '*** ALERTA VIENTO ***' if alerta_viento else 'Normal'
            print(f'[ECMWF] {nombre.upper()}: max {max_viento_kt} kt | '
                  f'racha {max_racha_kt} kt | lluvia {max_lluvia:.1f} mm | {estado}')

        except requests.RequestException as e:
            print(f'[ECMWF] Error consultando {nombre}: {e}')
            resultados[nombre] = None

    return resultados


# ─── Fuente 4: NOAA CO-OPS (nivel del mar) ────────────────────────────────────

def consultar_coops():
    """
    Nivel del mar en tiempo real. Critico para islas bajas como Providencia.
    Una marejada ciclonica puede llegar horas antes que los vientos maximos.
    Estacion de referencia: San Juan, Puerto Rico (proxy Caribe occidental).
    """
    print(f'[CO-OPS] Consultando estacion {COOPS_STATION_ID}...')
    try:
        url = COOPS_URL.format(station=COOPS_STATION_ID)
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()

        if 'error' in data:
            print(f'[CO-OPS] Error de la API: {data["error"]["message"]}')
            return None

        lecturas = data.get('data', [])
        if not lecturas:
            print('[CO-OPS] Sin datos de nivel del mar')
            return None

        # Ultima lectura disponible
        ultima = lecturas[-1]
        nivel_m = float(ultima.get('v', 0))
        hora    = ultima.get('t', '')

        # Sigma = desviacion estandar (indicador de turbulencia)
        sigma = float(ultima.get('s', 0))

        # Umbral de alerta: nivel > 0.5m sobre datum (marejada incipiente)
        alerta_marejada = nivel_m > 0.5

        resultado = {
            'fuente':          'NOAA CO-OPS',
            'estacion':        COOPS_STATION_ID,
            'nivel_m':         nivel_m,
            'sigma':           sigma,
            'hora_utc':        hora,
            'alerta_marejada': alerta_marejada,
        }

        estado = '*** ALERTA MAREJADA ***' if alerta_marejada else 'Normal'
        print(f'[CO-OPS] Nivel del mar: {nivel_m:.3f} m | sigma: {sigma} | {estado}')
        return resultado

    except requests.RequestException as e:
        print(f'[CO-OPS] No disponible: {e}')
        return None


# ─── Motor principal ──────────────────────────────────────────────────────────

def detectar_ciclones():
    """
    Consulta las 4 fuentes en secuencia y consolida el resultado.
    Retorna el JSON que se enviara al Service Bus de Azure.
    """
    print('=' * 60)
    print('ResiRed - Motor de Deteccion de Ciclones')
    print(f'Timestamp: {pd.Timestamp.now(tz="UTC")}')
    print('=' * 60)

    # Consultar las 4 fuentes
    ciclones_nhc  = consultar_nhc()
    alertas_gdacs = consultar_gdacs()
    pronostico    = consultar_ecmwf()
    nivel_mar     = consultar_coops()

    # Determinar nivel de alerta consolidado
    alerta_consolidada = 'verde'

    if ciclones_nhc:
        # El ciclon mas cercano determina el nivel
        mas_cercano = min(ciclones_nhc, key=lambda x: x['distancia_km'])
        alerta_consolidada = mas_cercano['nivel_alerta']

    elif alertas_gdacs:
        nivel_g = alertas_gdacs[0]['nivel_gdacs'].lower()
        if nivel_g == 'red':
            alerta_consolidada = 'rojo'
        elif nivel_g == 'orange':
            alerta_consolidada = 'naranja'

    # ECMWF puede subir a amarillo si hay viento fuerte sin ciclon confirmado
    if alerta_consolidada == 'verde' and pronostico:
        for isla, datos in pronostico.items():
            if datos and datos.get('alerta_viento'):
                alerta_consolidada = 'amarillo'
                break

    print('=' * 60)
    print(f'NIVEL DE ALERTA CONSOLIDADO: {alerta_consolidada.upper()}')
    print(f'Ciclones NHC detectados: {len(ciclones_nhc)}')
    print(f'Alertas GDACS:           {len(alertas_gdacs)}')
    print('=' * 60)

    resultado = {
        'nivel_alerta':    alerta_consolidada,
        'ciclones_nhc':    ciclones_nhc,
        'alertas_gdacs':   alertas_gdacs,
        'ecmwf':           pronostico,
        'nivel_mar_coops': nivel_mar,
        'timestamp':       str(pd.Timestamp.now(tz='UTC')),
        'version':         '1.0.0',
    }

    return resultado


# ─── Punto de entrada local ───────────────────────────────────────────────────
if __name__ == '__main__':
    resultado = detectar_ciclones()
    print('\n--- OUTPUT JSON ---')
    print(json.dumps(resultado, indent=2, default=str))