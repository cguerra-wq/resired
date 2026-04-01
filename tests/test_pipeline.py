# ResiRed - tests/test_pipeline.py
# Simula el flujo completo local sin Azure Service Bus:
# fn-gdacs-detector → [Service Bus] → fn-geo-intersection
# Ejecutar desde: C:\Users\cguerra\resired\

import sys
import json
import time
import importlib.util
from pathlib import Path

BASE = Path(__file__).parent.parent


def cargar_modulo(nombre, ruta):
    """Carga un modulo Python por ruta absoluta."""
    carpeta = str(ruta.parent)
    if carpeta not in sys.path:
        sys.path.insert(0, carpeta)
    spec = importlib.util.spec_from_file_location(nombre, ruta)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = mod
    spec.loader.exec_module(mod)
    return mod


# Cargar las dos funciones por ruta — evita conflicto de nombres
detector = cargar_modulo(
    "gdacs_detector",
    BASE / "functions" / "gdacs-detector" / "function.py"
)
geo = cargar_modulo(
    "geo_intersection",
    BASE / "functions" / "geo-intersection" / "function.py"
)

detectar_ciclones     = detector.detectar_ciclones
procesar_interseccion = geo.procesar_interseccion


def separador(titulo):
    print('\n' + '=' * 60)
    print(f'  {titulo}')
    print('=' * 60)


def correr_pipeline():
    """Pipeline completo ResiRed en modo local."""

    # PASO 1: Deteccion
    separador('PASO 1 — fn-gdacs-detector')
    t0 = time.time()
    evento = detectar_ciclones()
    t1 = time.time()

    print(f'\n[PIPELINE] Deteccion completada en {t1-t0:.1f}s')
    print(f'[PIPELINE] Nivel de alerta: {evento["nivel_alerta"].upper()}')
    print(f'[PIPELINE] Ciclones NHC:    {len(evento["ciclones_nhc"])}')
    print(f'[PIPELINE] Alertas GDACS:   {len(evento["alertas_gdacs"])}')

    # Simular Service Bus
    separador('SERVICE BUS — Transferencia del mensaje')
    mensaje_json = json.dumps(evento, default=str)
    print(f'[PIPELINE] Mensaje serializado: {len(mensaje_json)} bytes')
    print('[PIPELINE] → En Azure esto viajaria por la cola "cola-geo"')
    evento_recibido = json.loads(mensaje_json)
    print('[PIPELINE] Mensaje recibido por fn-geo-intersection OK')

    # PASO 2: Interseccion geoespacial
    separador('PASO 2 — fn-geo-intersection')
    t2 = time.time()
    resultado = procesar_interseccion(evento_recibido)
    t3 = time.time()
    print(f'\n[PIPELINE] Interseccion completada en {t3-t2:.1f}s')

    # Resumen final
    separador('RESUMEN DEL PIPELINE')
    nivel   = resultado['nivel_alerta'].upper()
    zonas   = resultado['zonas']
    resumen = resultado['resumen_por_isla']
    emojis  = {'rojo':'🔴','naranja':'🟠','amarillo':'🟡','verde':'🟢'}

    print(f'\n  NIVEL DE ALERTA GLOBAL: {nivel}')
    print(f'  Total zonas procesadas: {resultado["total_zonas"]}')
    print()

    for isla, conteo in resumen.items():
        print(f'  {isla}:')
        for nivel_z, n in conteo.items():
            if n > 0:
                print(f'    {emojis.get(nivel_z,"⚪")} {nivel_z.upper()}: {n} zonas')

    print()
    for nivel_z in ['rojo', 'naranja', 'amarillo']:
        if zonas[nivel_z]:
            print(f'  ZONAS {nivel_z.upper()} ({len(zonas[nivel_z])}):')
            for z in zonas[nivel_z]:
                print(f'    - {z}')

    print(f'\n  Tiempo total pipeline: {t3-t0:.1f}s')

    separador('SIGUIENTE → fn-adam-enricher')
    print('  En Azure este resultado entraria a la cola "cola-adam"')
    print('  para enriquecer con datos WFP ADAM y activar al Gobernador.')
    print()

    # Guardar output
    output_path = Path(__file__).parent / "output_pipeline.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(
            {'detector': evento, 'geo_intersection': resultado},
            f, indent=2, default=str, ensure_ascii=False
        )
    print(f'  Output guardado en: {output_path}')
    return resultado


if __name__ == '__main__':
    correr_pipeline()