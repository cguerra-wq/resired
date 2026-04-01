# ResiRed - fn-community-subscribe
# Mercy Corps Colombia - San Andres y Providencia
# Maneja la suscripcion al canal comunitario via:
# 1. Keyword WA (QR code o mensaje directo)
# 2. Registro manual por MEAL (via CommCare sync)
# En produccion: webhook HTTP de Twilio

import os
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv(Path(__file__).parent.parent.parent / ".env")

ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
AUTH_TOKEN  = os.getenv("TWILIO_AUTH_TOKEN")
FROM_WA     = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")

# Base de datos local (en produccion: Azure SQL)
DB_PATH = Path(__file__).parent.parent.parent / "tests" / "subscribers.db"

# Keywords que activan la suscripcion
KEYWORDS_SUSCRIBIR = [
    "hola resired", "suscribir", "suscribirme", "canal",
    "informacion", "información", "info", "unirme", "registro"
]

# Keywords para darse de baja
KEYWORDS_BAJA = ["salir", "baja", "cancelar", "stop", "no mas", "no más"]

# Mensaje de bienvenida
MSG_BIENVENIDA = (
    "Bienvenido al canal ResiRed de Mercy Corps Colombia.\n\n"
    "Este canal te mantendra informado sobre:\n"
    "Alertas de huracanes y tormentas en San Andres y Providencia\n"
    "Consejos de preparacion y seguridad\n"
    "Informacion sobre el programa de ayuda anticipatoria\n\n"
    "Responde SALIR en cualquier momento para darte de baja.\n\n"
    "ResiRed Mercy Corps Colombia"
)

MSG_BAJA = (
    "Has sido eliminado del canal ResiRed.\n"
    "Si deseas volver, escribe SUSCRIBIR.\n"
    "ResiRed Mercy Corps Colombia"
)

MSG_YA_SUSCRITO = (
    "Ya haces parte del canal ResiRed.\n"
    "Te seguiremos enviando informacion importante.\n"
    "Responde SALIR si deseas darte de baja.\n"
    "ResiRed Mercy Corps Colombia"
)


# ─── Base de datos local (placeholder para Azure SQL) ─────────────────────────

def init_db():
    """Crea la tabla de suscriptores si no existe."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS subscribers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            telefono    TEXT UNIQUE NOT NULL,
            nombre      TEXT,
            idioma      TEXT DEFAULT "es",
            fuente      TEXT DEFAULT "keyword",
            activo      INTEGER DEFAULT 1,
            suscrito_en TEXT,
            actualizado TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print(f'[SUBSCRIBE] Base de datos inicializada en: {DB_PATH}')


def esta_suscrito(telefono):
    """Verifica si un numero esta suscrito y activo."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        'SELECT activo FROM subscribers WHERE telefono = ?', (telefono,)
    ).fetchone()
    conn.close()
    if row is None:
        return None      # nunca estuvo
    return row[0] == 1   # True=activo, False=inactivo


def agregar_suscriptor(telefono, nombre=None, idioma="es", fuente="keyword"):
    """Agrega o reactiva un suscriptor."""
    conn = sqlite3.connect(DB_PATH)
    ahora = datetime.utcnow().isoformat()
    conn.execute('''
        INSERT INTO subscribers (telefono, nombre, idioma, fuente, activo, suscrito_en, actualizado)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(telefono) DO UPDATE SET
            activo = 1,
            fuente = excluded.fuente,
            actualizado = excluded.actualizado
    ''', (telefono, nombre, idioma, fuente, ahora, ahora))
    conn.commit()
    conn.close()
    print(f'[SUBSCRIBE] Suscriptor agregado/reactivado: {telefono} via {fuente}')


def dar_de_baja(telefono):
    """Desactiva un suscriptor."""
    conn = sqlite3.connect(DB_PATH)
    ahora = datetime.utcnow().isoformat()
    conn.execute(
        'UPDATE subscribers SET activo = 0, actualizado = ? WHERE telefono = ?',
        (ahora, telefono)
    )
    conn.commit()
    conn.close()
    print(f'[SUBSCRIBE] Suscriptor dado de baja: {telefono}')


def listar_suscriptores():
    """Retorna todos los suscriptores activos."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT telefono, nombre, idioma, fuente, suscrito_en FROM subscribers WHERE activo = 1'
    ).fetchall()
    conn.close()
    return [
        {'telefono': r[0], 'nombre': r[1], 'idioma': r[2],
         'fuente': r[3], 'suscrito_en': r[4]}
        for r in rows
    ]


# ─── Envio de mensajes de respuesta ───────────────────────────────────────────

def enviar_respuesta(destinatario, mensaje):
    """Envia WA de respuesta via Twilio."""
    try:
        client = Client(ACCOUNT_SID, AUTH_TOKEN)
        msg = client.messages.create(
            from_=FROM_WA,
            to=destinatario,
            body=mensaje
        )
        print(f'[SUBSCRIBE] Respuesta enviada a {destinatario}: {msg.sid}')
        return msg.sid
    except Exception as e:
        print(f'[SUBSCRIBE] Error enviando respuesta: {e}')
        return None


# ─── Procesamiento del mensaje entrante ───────────────────────────────────────

def procesar_mensaje_entrante(telefono, texto, nombre=None):
    """
    Procesa un mensaje WA entrante y determina la accion.
    En produccion: llamado desde el webhook de Twilio.

    Returns:
        dict con la accion tomada y el mensaje de respuesta
    """
    texto_lower = texto.lower().strip()
    estado = esta_suscrito(telefono)

    # ── Solicitud de BAJA ────────────────────────────────────
    if any(k in texto_lower for k in KEYWORDS_BAJA):
        if estado:
            dar_de_baja(telefono)
            enviar_respuesta(telefono, MSG_BAJA)
            return {'accion': 'baja', 'telefono': telefono, 'mensaje': MSG_BAJA}
        return {'accion': 'no_estaba_suscrito', 'telefono': telefono}

    # ── Solicitud de SUSCRIPCION ─────────────────────────────
    if any(k in texto_lower for k in KEYWORDS_SUSCRIBIR):
        if estado is True:
            enviar_respuesta(telefono, MSG_YA_SUSCRITO)
            return {'accion': 'ya_suscrito', 'telefono': telefono, 'mensaje': MSG_YA_SUSCRITO}

        agregar_suscriptor(telefono, nombre=nombre, fuente='keyword')
        enviar_respuesta(telefono, MSG_BIENVENIDA)
        return {'accion': 'suscrito', 'telefono': telefono, 'mensaje': MSG_BIENVENIDA}

    # ── Mensaje no reconocido ────────────────────────────────
    MSG_AYUDA = (
        "Hola, soy ResiRed de Mercy Corps Colombia.\n\n"
        "Para suscribirte al canal escribe: SUSCRIBIR\n"
        "Para darte de baja escribe: SALIR\n\n"
        "Para emergencias llama al 123."
    )
    enviar_respuesta(telefono, MSG_AYUDA)
    return {'accion': 'no_reconocido', 'telefono': telefono, 'texto': texto}


# ─── Registro manual por MEAL ─────────────────────────────────────────────────

def registrar_desde_meal(telefono, nombre, idioma="es"):
    """
    Registra un suscriptor manualmente (equipo MEAL en campo).
    En produccion: puede ser llamado por fn-commcare-extractor
    cuando detecta un nuevo hogar con telefono valido.
    """
    estado = esta_suscrito(telefono)
    if estado is True:
        print(f'[SUBSCRIBE] {telefono} ya esta suscrito')
        return {'accion': 'ya_suscrito', 'telefono': telefono}

    agregar_suscriptor(telefono, nombre=nombre, idioma=idioma, fuente='meal')
    enviar_respuesta(telefono, MSG_BIENVENIDA)
    return {'accion': 'suscrito_meal', 'telefono': telefono, 'nombre': nombre}


# ─── Punto de entrada local ───────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()

    print('\n=== PRUEBA fn-community-subscribe ===\n')

    # Simular 3 suscripciones
    print('--- Suscripcion 1: via keyword "SUSCRIBIR" ---')
    r1 = procesar_mensaje_entrante(
        telefono=os.getenv("GOBERNADOR_WHATSAPP", "whatsapp:+571234567890"),
        texto="Suscribir",
        nombre="Carlos Prueba"
    )
    print(json.dumps(r1, indent=2, default=str))

    print('\n--- Suscripcion 2: registro MEAL ---')
    r2 = registrar_desde_meal(
        telefono="whatsapp:+576001112222",
        nombre="Maria Lopez",
        idioma="es"
    )
    print(json.dumps(r2, indent=2, default=str))

    print('\n--- Intento doble suscripcion ---')
    r3 = procesar_mensaje_entrante(
        telefono=os.getenv("GOBERNADOR_WHATSAPP", "whatsapp:+571234567890"),
        texto="canal"
    )
    print(json.dumps(r3, indent=2, default=str))

    print('\n--- Suscriptores activos ---')
    subs = listar_suscriptores()
    print(f'Total: {len(subs)}')
    for s in subs:
        print(f'  {s["telefono"]} | {s["nombre"]} | {s["fuente"]}')
