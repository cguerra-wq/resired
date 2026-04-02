# ResiRed - Guia de importacion de Flows en Twilio Studio

## Los 3 flows de ResiRed

### Flow 1 - Router de mensajes entrantes (flow1_router.json)
Maneja TODOS los mensajes que llegan al numero WA.
- SI/NO → fn-governor-response
- SUSCRIBIR/CANAL/SALIR/INFO → fn-community-subscribe
- Cualquier otra cosa → mensaje de ayuda automatico

### Flow 2 - Gobernador CVA (flow2_gobernador.json)
Se activa desde el codigo Python (fn-governor-notify) via REST API.
- Envia el mensaje de alerta al Gobernador
- Espera respuesta 30 minutos (timeout)
- SI → activa CVA via webhook
- NO → registra rechazo
- Timeout → escala al delegado alterno

### Flow 3 - Alertas comunidad (flow3_alertas.json)
Se activa desde el codigo Python (fn-twilio-dispatcher) via REST API.
- alerta_naranja / alerta_rojo → alerta CVA completa
- alerta_amarillo → mensaje preventivo
- canal_contenido → contenido programado del canal

---

## Como importar en Twilio Studio

1. Ve a console.twilio.com
2. Clic en "Studio" en el menu izquierdo
3. Clic en "Create new Flow"
4. Nombre: "ResiRed - Router Mensajes" (o el nombre del flow)
5. Selecciona "Import from JSON"
6. Pega el contenido del archivo JSON correspondiente
7. Clic en "Next" y luego "Import"

---

## Que debes reemplazar en cada flow

Busca el texto REEMPLAZAR_CON_URL_AZURE y cambialo por:
- En desarrollo local con ngrok: https://TU_URL_NGROK
- En produccion Azure: https://TU_FUNCTION_APP.azurewebsites.net

Los endpoints que usa cada flow:
- /governor/response  → fn-governor-response
- /governor/timeout   → fn-governor-response (maneja timeout)
- /subscribe          → fn-community-subscribe
- /dispatcher/send    → fn-twilio-dispatcher
- /status/update      → fn-status-handler
- /errors/log         → logging general

---

## Como conectar Flow 1 al numero de Twilio

Despues de importar Flow 1:
1. Ve a Phone Numbers → Manage → Active Numbers
2. Clic en tu numero
3. En "Messaging" → "A message comes in"
4. Selecciona: Studio Flow
5. Selecciona: ResiRed - Router Mensajes
6. Clic en Save

Esto hace que TODOS los mensajes entrantes pasen por el router.

---

## Como activar Flow 2 y Flow 3 desde Python

Flow 2 (Gobernador) - se activa desde fn-governor-notify:
```python
client.studio.v2.flows("FLOW_SID_GOBERNADOR").executions.create(
    to="whatsapp:+57NUMERO_GOBERNADOR",
    from_="whatsapp:+14155238886",
    parameters={
        "gobernador_telefono": "whatsapp:+57NUMERO",
        "delegado_telefono": "whatsapp:+57NUMERO_DELEGADO",
        "evento_id": "EVT-2026-001",
        "nivel_alerta": "naranja",
        "mensaje_alerta": "🟠 ALERTA RESIRED - NIVEL NARANJA\n..."
    }
)
```

Flow 3 (Alertas) - se activa desde fn-twilio-dispatcher:
```python
client.studio.v2.flows("FLOW_SID_ALERTAS").executions.create(
    to="whatsapp:+57NUMERO_FAMILIA",
    from_="whatsapp:+14155238886",
    parameters={
        "tipo_alerta": "alerta_naranja",
        "destinatario": "whatsapp:+57NUMERO",
        "nivel_alerta": "naranja",
        "evento_id": "EVT-2026-001",
        "nombre": "Familia Lopez",
        "zona": "Centro / Sarie Bay",
        "es_adulto_mayor": "false",
        "mensaje": "ALERTA RESIRED..."
    }
)
```

---

## Orden de importacion recomendado

1. Primero: Flow 1 (Router) - conectarlo al numero
2. Segundo: Flow 2 (Gobernador)
3. Tercero: Flow 3 (Alertas)
4. Actualizar los SIDs en el .env:
   TWILIO_FLOW_SID_GOBERNADOR=FWxxxxxxxx
   TWILIO_FLOW_SID_ALERTAS=FWxxxxxxxx
