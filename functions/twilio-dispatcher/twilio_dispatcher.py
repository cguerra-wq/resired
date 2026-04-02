# ResiRed - fn-twilio-dispatcher
# Mercy Corps Colombia - San Andres y Providencia
# Envia alertas masivas a familias segun nivel de alerta y perfil de mensaje
# Perfiles: comunidad / entidades / mercy_corps / gobernador
# Canales: WA (primario) → SMS (fallback 3 min) → Voz (adultos mayores siempre)

import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv(Path(__file__).parent.parent.parent / ".env")

ACCOUNT_SID = os.getenv("AC079efda33443ad8fcabe5b493b04dca1")
AUTH_TOKEN  = os.getenv("Tc94d0a89249f662eadcc8f31723c94e7")
FROM_WA     = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")
FROM_SMS    = os.getenv("TWILIO_SMS_FROM", os.getenv("TWILIO_WHATSAPP_FROM", "").replace("whatsapp:", ""))
FROM_VOICE  = os.getenv("TWILIO_VOICE_FROM", FROM_SMS)

# ─── Templates de mensaje por perfil ──────────────────────────────────────────
# En produccion: templates aprobados por Meta (UTILITY category)
# En sandbox: texto libre

MENSAJES = {

    # ── COMUNIDAD: familias registradas en CommCare ───────────────────────────
    'comunidad_naranja': (
        "ALERTA RESIRED - NIVEL NARANJA\n\n"
        "Se ha detectado una tormenta tropical que puede afectar "
        "San Andres y Providencia en las proximas 48-72 horas.\n\n"
        "ACCIONES RECOMENDADAS:\n"
        "Asegure su vivienda y pertenencias\n"
        "Prepare un kit de emergencia (agua, alimentos, documentos)\n"
        "Identifique el punto de evacuacion mas cercano\n"
        "Mantenga su celular cargado\n\n"
        "El programa ResiRed esta activado. "
        "Recibira una transferencia anticipatoria si es elegible.\n\n"
        "ResiRed - Mercy Corps Colombia"
    ),
    'comunidad_rojo': (
        "ALERTA RESIRED - NIVEL ROJO\n\n"
        "PELIGRO INMINENTE: Huracan categoría {categoria} "
        "se acerca a San Andres y Providencia.\n\n"
        "ACCIONES INMEDIATAS:\n"
        "EVACUE AHORA si esta en zona costera o de inundacion\n"
        "Dirjase al punto de evacuacion asignado\n"
        "No regrese a su hogar hasta que las autoridades lo indiquen\n\n"
        "El programa ResiRed esta activado. "
        "Recibira una transferencia anticipatoria si es elegible.\n\n"
        "ResiRed - Mercy Corps Colombia\n"
        "Emergencias: 123"
    ),
    'comunidad_amarillo': (
        "AVISO RESIRED - NIVEL AMARILLO\n\n"
        "Se monitorea una perturbacion meteorologica en el Caribe. "
        "Por ahora no representa peligro inmediato.\n\n"
        "RECOMENDACIONES:\n"
        "Mantenga atencion a las noticias y alertas oficiales\n"
        "Revise que su kit de emergencia este listo\n"
        "Comparta esta informacion con su familia\n\n"
        "ResiRed - Mercy Corps Colombia"
    ),

    # ── ENTIDADES: UNGRD, Alcaldia, Cruz Roja ────────────────────────────────
    'entidades_naranja': (
        "INFORME TECNICO RESIRED\n"
        "Nivel: NARANJA | {timestamp}\n\n"
        "Sistema ResiRed ha detectado amenaza de ciclon tropical.\n"
        "Zonas en alerta: {zonas_criticas} zonas\n"
        "Familias potencialmente afectadas: {n_familias}\n\n"
        "Protocolo CVA anticipatorio: ACTIVADO\n"
        "Coordinador: Mercy Corps Colombia\n\n"
        "Para informacion tecnica detallada contacte:\n"
        "Carlos Guerra - cguerra@mercycorps.org\n\n"
        "ResiRed - Mercy Corps Colombia"
    ),
    'entidades_rojo': (
        "ALERTA MAXIMA - INFORME TECNICO RESIRED\n"
        "Nivel: ROJO | {timestamp}\n\n"
        "CICLON TROPICAL DE ALTA INTENSIDAD detectado.\n"
        "Categoria estimada: {categoria}\n"
        "Zonas en alerta roja: {zonas_rojas} zonas\n"
        "Familias en zona critica: {n_familias}\n\n"
        "Protocolo CVA anticipatorio: ACTIVADO\n"
        "Coordinacion con autoridades: REQUERIDA INMEDIATAMENTE\n\n"
        "ResiRed - Mercy Corps Colombia"
    ),

    # ── MERCY CORPS: equipo interno ───────────────────────────────────────────
    'mercy_corps_activacion': (
        "RESIRED - SISTEMA ACTIVADO\n"
        "Nivel: {nivel} | {timestamp}\n\n"
        "El Gobernador autorizo el protocolo CVA.\n\n"
        "Estado del sistema:\n"
        "Deteccion: OK\n"
        "Geo-interseccion: {total_zonas} zonas procesadas\n"
        "CVA activado: SI\n"
        "Alertas enviadas: EN PROCESO\n\n"
        "Dashboard: [URL cuando este disponible]\n\n"
        "ResiRed - Mercy Corps Colombia"
    ),

    # ── VOZ TTS: adultos mayores (siempre, sin importar nivel) ────────────────
    'voz_alerta': (
        "Atencion. Atencion. "
        "Este es un mensaje de Mercy Corps Colombia. "
        "El sistema ResiRed ha detectado una amenaza climatica "
        "que puede afectar San Andres y Providencia. "
        "Por favor tome precauciones. "
        "Asegure su vivienda. "
        "Prepare agua y alimentos para tres dias. "
        "Identifique el punto de evacuacion mas cercano a su hogar. "
        "Si necesita ayuda, llame al ciento veintitres. "
        "Este mensaje es de Mercy Corps Colombia. "
        "Repito: tome precauciones. "
        "Gracias."
    ),

    # ── CANAL COMUNITARIO: todos los suscriptores ─────────────────────────────
    'canal_alerta': (
        "ALERTA RESIRED - {nivel_texto}\n\n"
        "El sistema de alerta temprana de Mercy Corps Colombia "
        "ha detectado una amenaza en el Caribe.\n\n"
        "{mensaje_nivel}\n\n"
        "Mantenga su celular cargado y siga las instrucciones "
        "de las autoridades locales.\n\n"
        "Mas informacion: escriba INFO\n"
        "ResiRed - Mercy Corps Colombia"
    ),
}


# ─── Envio de mensajes ────────────────────────────────────────────────────────

def enviar_wa(client, telefono, mensaje):
    """Envia WA. Retorna el SID o None si falla."""
    try:
        msg = client.messages.create(
            from_=FROM_WA,
            to=telefono if telefono.startswith('whatsapp:') else f'whatsapp:{telefono}',
            body=mensaje
        )
        return {'sid': msg.sid, 'status': msg.status, 'canal': 'wa'}
    except Exception as e:
        print(f'  [WA] Error enviando a {telefono}: {e}')
        return None


def enviar_sms(client, telefono, mensaje):
    """Envia SMS como fallback."""
    try:
        numero = telefono.replace('whatsapp:', '')
        msg = client.messages.create(
            from_=FROM_SMS,
            to=numero,
            body=mensaje[:160]  # SMS limit
        )
        return {'sid': msg.sid, 'status': msg.status, 'canal': 'sms'}
    except Exception as e:
        print(f'  [SMS] Error enviando a {telefono}: {e}')
        return None


def enviar_voz(client, telefono, mensaje_tts):
    """Envia llamada de voz TTS a adultos mayores."""
    try:
        numero = telefono.replace('whatsapp:', '')
        twiml = f'<Response><Say language="es-MX" voice="Polly.Mia">{mensaje_tts}</Say></Response>'
        call = client.calls.create(
            from_=FROM_VOICE,
            to=numero,
            twiml=twiml
        )
        return {'sid': call.sid, 'status': call.status, 'canal': 'voz'}
    except Exception as e:
        print(f'  [VOZ] Error llamando a {telefono}: {e}')
        return None


# ─── Dispatcher principal ─────────────────────────────────────────────────────

def despachar_alertas(evento_cva):
    """
    Recibe el evento CVA activado y envia alertas a todas las listas.
    evento_cva debe tener:
      - nivel_alerta: rojo/naranja/amarillo
      - familias: lista de {telefono, nombre, adulto_mayor, zona}
      - entidades: lista de {telefono, nombre, organizacion}
      - mercy_corps: lista de {telefono, nombre}
      - suscriptores_canal: lista de {telefono}
      - resumen: {zonas_criticas, n_familias, categoria}
    """
    nivel     = evento_cva.get('nivel_alerta', 'naranja')
    familias  = evento_cva.get('familias', [])
    entidades = evento_cva.get('entidades', [])
    mc_equipo = evento_cva.get('mercy_corps', [])
    canal     = evento_cva.get('suscriptores_canal', [])
    resumen   = evento_cva.get('resumen', {})
    timestamp = datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')

    client   = Client(ACCOUNT_SID, AUTH_TOKEN)
    log      = []
    enviados = {'wa': 0, 'sms': 0, 'voz': 0, 'fallidos': 0}

    print('=' * 60)
    print(f'ResiRed - fn-twilio-dispatcher')
    print(f'Nivel: {nivel.upper()} | {timestamp}')
    print(f'Familias: {len(familias)} | Entidades: {len(entidades)} | Canal: {len(canal)}')
    print('=' * 60)

    # ── 1. Alertas a familias (perfil COMUNIDAD) ──────────────────────────────
    print(f'\n[DISPATCHER] Enviando a {len(familias)} familias...')
    msg_comunidad = MENSAJES.get(
        f'comunidad_{nivel}',
        MENSAJES['comunidad_naranja']
    ).format(
        categoria=resumen.get('categoria', '?'),
        n_familias=len(familias),
        zonas_criticas=resumen.get('zonas_criticas', 0),
        timestamp=timestamp
    )

    for familia in familias:
        tel  = familia.get('telefono', '')
        nombre = familia.get('nombre', 'Familia')
        es_adulto_mayor = familia.get('adulto_mayor', False)

        if not tel:
            continue

        print(f'  → {nombre} ({tel})')

        # Siempre intentar WA primero
        resultado = enviar_wa(client, tel, msg_comunidad)

        if resultado:
            enviados['wa'] += 1
            print(f'    WA: {resultado["sid"]}')
        else:
            # Fallback a SMS
            resultado = enviar_sms(client, tel, msg_comunidad)
            if resultado:
                enviados['sms'] += 1
                print(f'    SMS fallback: {resultado["sid"]}')
            else:
                enviados['fallidos'] += 1

        # Voz SIEMPRE para adultos mayores
        if es_adulto_mayor:
            print(f'    VOZ (adulto mayor): iniciando llamada...')
            resultado_voz = enviar_voz(client, tel, MENSAJES['voz_alerta'])
            if resultado_voz:
                enviados['voz'] += 1
                print(f'    VOZ: {resultado_voz["sid"]}')

        log.append({
            'telefono': tel,
            'nombre': nombre,
            'perfil': 'comunidad',
            'resultado': resultado,
            'timestamp': timestamp
        })

        time.sleep(0.2)  # Rate limiting

    # ── 2. Alertas a entidades gubernamentales ────────────────────────────────
    print(f'\n[DISPATCHER] Enviando a {len(entidades)} entidades...')
    msg_entidades = MENSAJES.get(
        f'entidades_{nivel}',
        MENSAJES['entidades_naranja']
    ).format(
        timestamp=timestamp,
        zonas_criticas=resumen.get('zonas_criticas', 0),
        zonas_rojas=resumen.get('zonas_rojas', 0),
        n_familias=len(familias),
        categoria=resumen.get('categoria', '?')
    )

    for entidad in entidades:
        tel = entidad.get('telefono', '')
        if not tel:
            continue
        print(f'  → {entidad.get("nombre")} - {entidad.get("organizacion")}')
        resultado = enviar_wa(client, tel, msg_entidades)
        if resultado:
            enviados['wa'] += 1
        log.append({'telefono': tel, 'perfil': 'entidades', 'resultado': resultado})
        time.sleep(0.2)

    # ── 3. Alerta interna Mercy Corps ─────────────────────────────────────────
    print(f'\n[DISPATCHER] Enviando a {len(mc_equipo)} miembros de Mercy Corps...')
    msg_mc = MENSAJES['mercy_corps_activacion'].format(
        nivel=nivel.upper(),
        timestamp=timestamp,
        total_zonas=resumen.get('total_zonas', 39)
    )

    for miembro in mc_equipo:
        tel = miembro.get('telefono', '')
        if not tel:
            continue
        print(f'  → {miembro.get("nombre")}')
        resultado = enviar_wa(client, tel, msg_mc)
        if resultado:
            enviados['wa'] += 1
        log.append({'telefono': tel, 'perfil': 'mercy_corps', 'resultado': resultado})
        time.sleep(0.2)

    # ── 4. Broadcast al canal comunitario ─────────────────────────────────────
    print(f'\n[DISPATCHER] Broadcast a {len(canal)} suscriptores del canal...')
    nivel_texto = {'rojo': 'NIVEL ROJO', 'naranja': 'NIVEL NARANJA', 'amarillo': 'NIVEL AMARILLO'}.get(nivel, nivel.upper())
    mensaje_nivel_canal = {
        'rojo': 'EVACUACION RECOMENDADA. Sigua las instrucciones de las autoridades.',
        'naranja': 'Prepare su kit de emergencia y este atento a las alertas oficiales.',
        'amarillo': 'No hay peligro inmediato. Mantenga la atencion a las noticias.'
    }.get(nivel, '')

    msg_canal = MENSAJES['canal_alerta'].format(
        nivel_texto=nivel_texto,
        mensaje_nivel=mensaje_nivel_canal
    )

    for suscriptor in canal:
        tel = suscriptor.get('telefono', '')
        if not tel:
            continue
        resultado = enviar_wa(client, tel, msg_canal)
        if resultado:
            enviados['wa'] += 1
        time.sleep(0.2)

    # ── Resumen ───────────────────────────────────────────────────────────────
    print('\n' + '=' * 60)
    print('RESUMEN DE DESPACHO:')
    print(f'  WA enviados:  {enviados["wa"]}')
    print(f'  SMS enviados: {enviados["sms"]}')
    print(f'  Llamadas voz: {enviados["voz"]}')
    print(f'  Fallidos:     {enviados["fallidos"]}')
    print('=' * 60)

    return {
        'enviados': enviados,
        'total': sum(enviados.values()),
        'log': log,
        'timestamp': timestamp
    }


# ─── Punto de entrada local ───────────────────────────────────────────────────

if __name__ == '__main__':
    # Datos de prueba con tu numero real
    telefono_prueba = os.getenv("GOBERNADOR_WHATSAPP", "whatsapp:+571234567890")

    evento_prueba = {
        'nivel_alerta': 'naranja',
        'familias': [
            {'telefono': telefono_prueba, 'nombre': 'Familia Prueba 1',
             'adulto_mayor': False, 'zona': 'Centro / Sarie Bay'},
        ],
        'entidades': [],
        'mercy_corps': [],
        'suscriptores_canal': [],
        'resumen': {
            'zonas_criticas': 5,
            'zonas_rojas': 2,
            'n_familias': 1,
            'categoria': 2,
            'total_zonas': 39
        }
    }

    print('=== PRUEBA fn-twilio-dispatcher ===')
    print(f'Enviando alerta NARANJA a: {telefono_prueba}\n')
    resultado = despachar_alertas(evento_prueba)
    print('\n--- OUTPUT ---')
    print(json.dumps(resultado, indent=2, default=str))
