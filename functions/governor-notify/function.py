# ResiRed - fn-governor-notify
# Mercy Corps Colombia - San Andres y Providencia
# Envia mensaje WA Interactive al Gobernador cuando se detecta un ciclon
# En produccion: disparado por Azure Service Bus cola "cola-governor"
# En desarrollo: llamado directamente desde test_pipeline.py

import os
import json
from datetime import datetime
from dotenv import load_dotenv
from twilio.rest import Client
from pathlib import Path

# Cargar variables de entorno desde .env
load_dotenv(Path(__file__).parent.parent.parent / ".env")

ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN")
FROM_WA      = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
GOBERNADOR   = os.getenv("GOBERNADOR_WHATSAPP")


def construir_mensaje(geo_resultado):
    """
    Construye el texto del mensaje para el Gobernador
    basado en el nivel de alerta y las zonas afectadas.
    """
    nivel     = geo_resultado.get('nivel_alerta', 'verde').upper()
    zonas     = geo_resultado.get('zonas', {})
    resumen   = geo_resultado.get('resumen_por_isla', {})
    timestamp = datetime.utcnow().strftime('%d %b %Y %H:%M UTC')

    # Emojis por nivel
    emoji = {'ROJO': '🔴', 'NARANJA': '🟠', 'AMARILLO': '🟡', 'VERDE': '🟢'}
    icono = emoji.get(nivel, '⚪')

    # Resumen de zonas afectadas
    zonas_criticas = zonas.get('rojo', []) + zonas.get('naranja', [])
    n_criticas = len(zonas_criticas)
    n_amarillo = len(zonas.get('amarillo', []))

    # Resumen por isla
    resumen_texto = ''
    for isla, conteo in resumen.items():
        afectadas = conteo.get('rojo', 0) + conteo.get('naranja', 0) + conteo.get('amarillo', 0)
        if afectadas > 0:
            resumen_texto += f'\n  • {isla}: {afectadas} zonas en alerta'

    mensaje = (
        f'{icono} *ALERTA RESIRED — NIVEL {nivel}*\n'
        f'━━━━━━━━━━━━━━━━━━━━\n'
        f'*Fecha:* {timestamp}\n\n'
        f'*Zonas en alerta critica:* {n_criticas}\n'
        f'*Zonas en alerta media:* {n_amarillo}\n'
    )

    if resumen_texto:
        mensaje += f'\n*Por isla:*{resumen_texto}\n'

    if zonas_criticas:
        mensaje += f'\n*Zonas criticas:*\n'
        for z in zonas_criticas[:5]:  # Mostrar max 5
            mensaje += f'  • {z}\n'
        if len(zonas_criticas) > 5:
            mensaje += f'  • ... y {len(zonas_criticas) - 5} mas\n'

    mensaje += (
        f'\n━━━━━━━━━━━━━━━━━━━━\n'
        f'*¿Autoriza la activacion del protocolo CVA anticipatorio?*\n\n'
        f'Responda: *SI* para activar\n'
        f'Responda: *NO* para rechazar\n\n'
        f'_ResiRed · Mercy Corps Colombia_'
    )

    return mensaje


def notificar_gobernador(geo_resultado):
    """
    Envia el mensaje WA al Gobernador y retorna el SID del mensaje.
    En modo sandbox de Twilio: funciona sin templates aprobados.
    En produccion: usara el template aprobado por Meta.
    """
    print('[GOVERNOR] Preparando notificacion al Gobernador...')

    if not ACCOUNT_SID or not AUTH_TOKEN:
        print('[GOVERNOR] ERROR: Credenciales Twilio no configuradas en .env')
        return None

    if not GOBERNADOR:
        print('[GOVERNOR] ERROR: GOBERNADOR_WHATSAPP no configurado en .env')
        return None

    nivel = geo_resultado.get('nivel_alerta', 'verde')

    # Solo notificar si hay alerta real (no verde)
    if nivel == 'verde':
        print('[GOVERNOR] Nivel VERDE — sin notificacion al Gobernador')
        return {'status': 'skipped', 'razon': 'nivel_verde'}

    mensaje = construir_mensaje(geo_resultado)

    print(f'[GOVERNOR] Enviando WA a: {GOBERNADOR}')
    print(f'[GOVERNOR] Desde: {FROM_WA}')
    print(f'[GOVERNOR] Nivel de alerta: {nivel.upper()}')

    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)

        message = client.messages.create(
            from_=FROM_WA,
            to=GOBERNADOR,
            body=mensaje
        )

        print(f'[GOVERNOR] ✅ Mensaje enviado exitosamente')
        print(f'[GOVERNOR] SID: {message.sid}')
        print(f'[GOVERNOR] Status: {message.status}')

        return {
            'status':  'enviado',
            'sid':     message.sid,
            'estado':  message.status,
            'a':       GOBERNADOR,
            'nivel':   nivel,
            'timestamp': str(datetime.utcnow()),
        }

    except Exception as e:
        print(f'[GOVERNOR] ❌ Error enviando mensaje: {e}')
        return {
            'status': 'error',
            'error':  str(e),
            'nivel':  nivel,
        }


# ─── Punto de entrada local ───────────────────────────────────────────────────
if __name__ == '__main__':
    # Simular un evento nivel NARANJA para probar el envio real
    evento_prueba = {
        'nivel_alerta': 'naranja',
        'zonas': {
            'rojo':     ['Centro / Sarie Bay', 'Las Gaviotas'],
            'naranja':  ['San Luis (Casco principal)', 'Sound Bay', 'Free Town'],
            'amarillo': ['La Loma (Casco principal)', 'Santa Isabel (Town - Cabecera municipal)'],
            'verde':    []
        },
        'resumen_por_isla': {
            'San Andres':    {'rojo': 2, 'naranja': 2, 'amarillo': 1, 'verde': 25},
            'Providencia':   {'rojo': 0, 'naranja': 1, 'amarillo': 1, 'verde': 8},
            'Santa Catalina':{'rojo': 0, 'naranja': 0, 'amarillo': 0, 'verde': 1},
        },
        'total_zonas': 39,
    }

    print('=== PRUEBA fn-governor-notify ===')
    print('Enviando WA de prueba al numero configurado en .env...\n')

    resultado = notificar_gobernador(evento_prueba)

    print('\n--- OUTPUT ---')
    print(json.dumps(resultado, indent=2, default=str))
