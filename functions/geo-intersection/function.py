# ResiRed - fn-geo-intersection
# Mercy Corps Colombia - San Andres y Providencia
# Intersecta polígonos de zonas CommCare vs radios de viento NHC
# Basado en utils.py de AAAStorms (mc-t4d) - CC BY-NC 4.0

import json
import math
import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon, shape
from pathlib import Path

# ─── Rutas ────────────────────────────────────────────────────────────────────
ZONAS_GEOJSON = Path(__file__).parent.parent.parent / "geodata" / "zonas_san_andres.geojson"

# Radios de viento NHC (en nudos) → nivel de alerta ResiRed
# 64 kt = vientos de huracan        → ROJO
# 50 kt = vientos destructivos      → NARANJA
# 34 kt = tormenta tropical         → AMARILLO
RADIOS_NHC = {
    64: 'rojo',
    50: 'naranja',
    34: 'amarillo',
}


# ─── Carga de zonas ───────────────────────────────────────────────────────────

def cargar_zonas():
    """Carga el GeoJSON de zonas CommCare como GeoDataFrame."""
    try:
        gdf = gpd.read_file(ZONAS_GEOJSON)
        gdf = gdf.set_crs('EPSG:4326')
        print(f'[GEO] Zonas cargadas: {len(gdf)} zonas en el sistema')
        return gdf
    except Exception as e:
        print(f'[GEO] Error cargando zonas: {e}')
        return None


# ─── Interseccion por radio de viento ─────────────────────────────────────────

def zona_en_poligono_nhc(zona_geom, wind_gdf, radio_kt):
    """
    Verifica si una zona CommCare intersecta con el radio de viento del NHC.

    Args:
        zona_geom: geometria Shapely de la zona
        wind_gdf: GeoDataFrame con los polígonos del NHC (shapefiles de radios)
        radio_kt: radio de viento en nudos (34, 50 o 64)

    Returns:
        True si hay interseccion, False si no
    """
    try:
        # Filtrar el shapefile NHC por radio de viento
        wind_radio = wind_gdf[wind_gdf.get('RADII', wind_gdf.get('RAD', 0)) == radio_kt]
        if wind_radio.empty:
            return False

        for _, row in wind_radio.iterrows():
            if zona_geom.intersects(row.geometry):
                return True
        return False
    except Exception as e:
        print(f'[GEO] Error en interseccion kt={radio_kt}: {e}')
        return False


def intersectar_con_ciclon(ciclon, zonas_gdf):
    """
    Para un ciclon con wind_forecast (shapefiles NHC descargados),
    determina qué zonas de CommCare quedan dentro de cada radio de viento.

    Cuando no hay shapefiles (fuera de temporada), usa el radio Haversine
    como fallback basado en la posicion del ciclon.

    Returns:
        dict con zonas clasificadas por nivel de alerta
    """
    nombre = ciclon.get('nombre', 'DESCONOCIDO')
    lat    = ciclon.get('lat', 0)
    lon    = ciclon.get('lon', 0)
    wind_f = ciclon.get('wind_forecast', {})

    print(f'[GEO] Intersectando zonas para ciclon: {nombre}')

    resultado_zonas = {
        'rojo':     [],
        'naranja':  [],
        'amarillo': [],
        'verde':    [],
    }

    # ── Opcion A: shapefiles NHC disponibles (temporada activa) ──────────────
    wind_status = wind_f.get('status', False) if isinstance(wind_f, dict) else False

    if wind_status and isinstance(wind_f, dict):
        forecast = wind_f.get('forecast', [])
        print(f'[GEO] Usando shapefiles NHC ({len(forecast)} registros)')

        # Reconstruir GeoDataFrame desde el forecast descargado
        try:
            wind_gdf = gpd.GeoDataFrame(forecast, crs='EPSG:4326')

            for _, zona in zonas_gdf.iterrows():
                geom     = zona.geometry
                zona_id  = zona['zona_commcare']
                asignado = False

                for radio_kt, nivel in sorted(RADIOS_NHC.items(), reverse=True):
                    if zona_en_poligono_nhc(geom, wind_gdf, radio_kt):
                        resultado_zonas[nivel].append(zona_id)
                        asignado = True
                        break

                if not asignado:
                    resultado_zonas['verde'].append(zona_id)

        except Exception as e:
            print(f'[GEO] Error con shapefiles, usando fallback Haversine: {e}')
            wind_status = False  # forzar fallback

    # ── Opcion B: fallback Haversine (sin shapefiles o error) ─────────────────
    if not wind_status:
        print(f'[GEO] Usando fallback Haversine desde posicion ({lat}, {lon})')
        cat = ciclon.get('categoria', 0)
        vel_kt = ciclon.get('velocidad_kt', 0)

        # Radios aproximados por categoria (km) cuando no hay shapefiles
        # Basados en climatologia historica del Atlantico
        radios_km = {
            64: max(50,  vel_kt * 0.5),   # radio vientos huracan
            50: max(100, vel_kt * 1.0),   # radio vientos destructivos
            34: max(200, vel_kt * 2.0),   # radio tormenta tropical
        }

        for _, zona in zonas_gdf.iterrows():
            centroide = zona.geometry.centroid
            z_lat = centroide.y
            z_lon = centroide.x
            zona_id = zona['zona_commcare']

            dist = haversine_km(lat, lon, z_lat, z_lon)
            asignado = False

            for radio_kt, nivel in sorted(RADIOS_NHC.items(), reverse=True):
                if dist <= radios_km[radio_kt]:
                    resultado_zonas[nivel].append(zona_id)
                    asignado = True
                    break

            if not asignado:
                resultado_zonas['verde'].append(zona_id)

    return resultado_zonas


# ─── Resumen por isla ─────────────────────────────────────────────────────────

def resumir_por_isla(zonas_clasificadas, zonas_gdf):
    """
    Agrega el resultado de la interseccion por isla.
    Util para el mensaje del Gobernador y para CommCare.
    """
    resumen = {}

    for nivel, lista_zonas in zonas_clasificadas.items():
        for zona_id in lista_zonas:
            fila = zonas_gdf[zonas_gdf['zona_commcare'] == zona_id]
            if fila.empty:
                continue
            isla = fila.iloc[0]['isla']
            if isla not in resumen:
                resumen[isla] = {'rojo': 0, 'naranja': 0, 'amarillo': 0, 'verde': 0}
            resumen[isla][nivel] += 1

    return resumen


# ─── Funcion principal ────────────────────────────────────────────────────────

def procesar_interseccion(evento_detector):
    """
    Recibe el JSON de fn-gdacs-detector y retorna
    la clasificacion de zonas por nivel de alerta.

    Este es el output que va al Service Bus y luego
    a fn-commcare-extractor para filtrar las familias.
    """
    print('=' * 60)
    print('ResiRed - Motor de Interseccion Geoespacial')
    print('=' * 60)

    zonas_gdf = cargar_zonas()
    if zonas_gdf is None:
        return {'error': 'No se pudieron cargar las zonas'}

    nivel_global   = evento_detector.get('nivel_alerta', 'verde')
    ciclones       = evento_detector.get('ciclones_nhc', [])
    alertas_gdacs  = evento_detector.get('alertas_gdacs', [])

    # Sin amenaza activa → todas las zonas en verde
    if nivel_global == 'verde' and not ciclones and not alertas_gdacs:
        print('[GEO] Nivel VERDE — todas las zonas sin alerta')
        zonas_clasificadas = {
            'rojo':     [],
            'naranja':  [],
            'amarillo': [],
            'verde':    list(zonas_gdf['zona_commcare']),
        }
        resumen_isla = resumir_por_isla(zonas_clasificadas, zonas_gdf)

        return {
            'nivel_alerta':     'verde',
            'zonas':            zonas_clasificadas,
            'resumen_por_isla': resumen_isla,
            'total_zonas':      len(zonas_gdf),
            'ciclones_procesados': 0,
            'timestamp':        str(pd.Timestamp.now(tz='UTC')),
        }

    # Hay ciclones → intersectar con cada uno y tomar el peor nivel
    zonas_clasificadas = {
        'rojo':     [],
        'naranja':  [],
        'amarillo': [],
        'verde':    [],
    }

    for ciclon in ciclones:
        resultado = intersectar_con_ciclon(ciclon, zonas_gdf)

        # Combinar: una zona toma el nivel mas severo entre todos los ciclones
        for nivel in ['rojo', 'naranja', 'amarillo', 'verde']:
            for zona in resultado[nivel]:
                # Verificar que no este ya en un nivel mas severo
                ya_asignada = any(
                    zona in zonas_clasificadas[n]
                    for n in ['rojo', 'naranja', 'amarillo']
                    if n != nivel
                )
                if not ya_asignada and zona not in zonas_clasificadas[nivel]:
                    zonas_clasificadas[nivel].append(zona)

    # Zonas no tocadas por ningun ciclon → verde
    todas = set(zonas_gdf['zona_commcare'])
    asignadas = set(
        z for nivel in zonas_clasificadas.values() for z in nivel
    )
    zonas_clasificadas['verde'].extend(list(todas - asignadas))

    resumen_isla = resumir_por_isla(zonas_clasificadas, zonas_gdf)

    print(f'[GEO] Resultado:')
    print(f'      ROJO:     {len(zonas_clasificadas["rojo"])} zonas')
    print(f'      NARANJA:  {len(zonas_clasificadas["naranja"])} zonas')
    print(f'      AMARILLO: {len(zonas_clasificadas["amarillo"])} zonas')
    print(f'      VERDE:    {len(zonas_clasificadas["verde"])} zonas')

    return {
        'nivel_alerta':        nivel_global,
        'zonas':               zonas_clasificadas,
        'resumen_por_isla':    resumen_isla,
        'total_zonas':         len(zonas_gdf),
        'ciclones_procesados': len(ciclones),
        'timestamp':           str(pd.Timestamp.now(tz='UTC')),
    }


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ─── Punto de entrada local ───────────────────────────────────────────────────
if __name__ == '__main__':
    # Simular el output del fn-gdacs-detector (nivel verde, sin ciclones)
    evento_prueba = {
        'nivel_alerta': 'verde',
        'ciclones_nhc': [],
        'alertas_gdacs': [],
        'ecmwf': None,
        'nivel_mar_coops': None,
        'timestamp': str(pd.Timestamp.now(tz='UTC')),
    }

    resultado = procesar_interseccion(evento_prueba)
    print('\n--- OUTPUT JSON ---')
    print(json.dumps(resultado, indent=2, default=str))
