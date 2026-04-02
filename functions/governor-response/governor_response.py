# ResiRed - fn-governor-response
# Mercy Corps Colombia - San Andres y Providencia
# Webhook que recibe la respuesta SI/NO del Gobernador via Twilio
# En produccion: Azure Function HTTP trigger
# En desarrollo: Flask + ngrok

import os
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, Response
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv(Path(__file__).parent.parent.parent / ".env")

ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN")
FROM_WA      = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
GOBERNADOR   = os.getenv("GOBERNADOR_WHATSAPP")

# Base de datos de decisiones (en produccion: Azure SQL)
DB_PATH = Path(__file__).parent.parent.parent / "tests" / "decisions.db"

app = Flask(__name__)


# ─── Base de datos local ───────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS decisiones (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            evento_id    TEXT,
            nivel_alerta TEXT,
            decision     TEXT,
            telefono     TEXT,
            timestamp    TEXT,
            procesado    INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()


def guardar_decision(evento_id, nivel, decision, telefono):
    conn = sqlite3.connect(DB_PATH)
    ahora = datetime.now(timezone.utc).isoformat()
    conn.execute('''
        INSERT INTO decisiones (evento_id, nivel_alerta, decision, telefono, timestamp)
        VALUES (?, ?, ?, ?, ?)
    ''', (evento_id, nivel, decision, telefono, ahora))
    conn.commit()
    conn.close()
    print(f'[GOVERNOR-RESP] Decision guardada: {decision} | nivel: {nivel} | {ahora}')


# ─── Envio de confirmacion ────────────────────────────────────────────────────

def enviar_confirmacion(decision):
    """Envia WA de confirmacion al Gobernador."""
    client = Client(ACCOUNT_SID, AUTH_TOKEN)

    if decision == 'SI':
        msg = (
            "Protocolo CVA activado.\n\n"
            "El sistema esta procesando la lista de familias "
            "y generando el archivo de pagos.\n"
            "Recibirá una confirmación cuando el proceso esté completo.\n\n"
            "ResiRed · Mercy Corps Colombia"
        )
    else:
        msg = (
            "Decisión registrada: NO activar.\n\n"
            "El sistema seguirá monitoreando la situación.\n"
            "Si la amenaza aumenta, recibirá una nueva notificación.\n\n"
            "ResiRed · Mercy Corps Colombia"
        )

    try:
        message = client.messages.create(
            from_=FROM_WA,
            to=GOBERNADOR,
            body=msg
        )
        print(f'[GOVERNOR-RESP] Confirmacion enviada: {message.sid}')
    except Exception as e:
        print(f'[GOVERNOR-RESP] Error enviando confirmacion: {e}')


def activar_cva():
    """
    Simula la activacion del CVA.
    En produccion: encola mensaje en Azure Service Bus cola-cva
    """
    print('[GOVERNOR-RESP] *** CVA ACTIVADO ***')
    print('[GOVERNOR-RESP] → Encolar en Service Bus: cola-cva')
    print('[GOVERNOR-RESP] → fn-commcare-extractor iniciara en segundos')
    print('[GOVERNOR-RESP] → fn-csv-generator seguira a continuacion')

    # Guardar estado en archivo para que el pipeline lo detecte
    estado_path = Path(__file__).parent.parent.parent / "tests" / "cva_activado.json"
    estado = {
        'activado': True,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'activado_por': 'gobernador'
    }
    with open(estado_path, 'w') as f:
        json.dump(estado, f, indent=2)
    print(f'[GOVERNOR-RESP] Estado CVA guardado en: {estado_path}')


# ─── Webhook principal ────────────────────────────────────────────────────────

@app.route('/governor/response', methods=['POST'])
def governor_response():
    """
    Recibe el mensaje WA del Gobernador via Twilio webhook.
    Twilio hace POST con: From, Body, y otros metadatos.
    """
    telefono  = request.form.get('From', '')
    mensaje   = request.form.get('Body', '').strip().upper()
    num_media = request.form.get('NumMedia', '0')

    print(f'\n[GOVERNOR-RESP] Mensaje recibido de: {telefono}')
    print(f'[GOVERNOR-RESP] Contenido: "{mensaje}"')

    resp = MessagingResponse()

    # Verificar que es el Gobernador o delegado
    if GOBERNADOR and telefono not in [GOBERNADOR]:
        print(f'[GOVERNOR-RESP] Numero no autorizado: {telefono}')
        resp.message("Numero no autorizado para este protocolo.")
        return Response(str(resp), mimetype='text/xml')

    # Procesar SI
    if mensaje in ['SI', 'SÍ', 'S', 'YES', 'ACTIVAR', '1']:
        print('[GOVERNOR-RESP] *** GOBERNADOR DIJO SI ***')
        guardar_decision('evento_actual', 'naranja', 'SI', telefono)
        enviar_confirmacion('SI')
        activar_cva()
        resp.message("Confirmado. Protocolo CVA en ejecucion.")

    # Procesar NO
    elif mensaje in ['NO', 'N', '2', 'RECHAZAR', 'CANCELAR']:
        print('[GOVERNOR-RESP] Gobernador dijo NO')
        guardar_decision('evento_actual', 'naranja', 'NO', telefono)
        enviar_confirmacion('NO')
        resp.message("Registrado. Sistema en modo monitoreo.")

    # Respuesta no reconocida
    else:
        print(f'[GOVERNOR-RESP] Respuesta no reconocida: "{mensaje}"')
        resp.message(
            "Respuesta no reconocida.\n\n"
            "Responda SI para activar el protocolo CVA\n"
            "Responda NO para rechazar\n\n"
            "ResiRed · Mercy Corps Colombia"
        )

    return Response(str(resp), mimetype='text/xml')


@app.route('/health', methods=['GET'])
def health():
    """Endpoint de verificacion — confirma que el servidor esta vivo."""
    return {'status': 'ok', 'servicio': 'fn-governor-response', 'version': '1.0.0'}


# ─── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print('=' * 60)
    print('ResiRed - fn-governor-response')
    print('Servidor webhook esperando respuesta del Gobernador...')
    print()
    print('URL local:  http://localhost:5000/governor/response')
    print('Configurar en Twilio:')
    print('  https://TU_URL_NGROK/governor/response')
    print()
    print('Esperando mensajes... (Ctrl+C para detener)')
    print('=' * 60)
    app.run(port=5000, debug=True, use_reloader=False)
