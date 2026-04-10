"""
ResiRed - fn-gdacs-detector
Azure Functions v2 — Timer Trigger
Detecta amenazas meteorológicas cada 6 minutos y publica en Service Bus.
"""
import azure.functions as func
import logging
import json
import os
from azure.servicebus import ServiceBusClient, ServiceBusMessage

# Importar lógica existente (sin cambios)
from .parse_storms import consultar_nhc, consultar_gdacs, consultar_ecmwf, consultar_coops

app = func.FunctionApp()

@app.timer_trigger(
    schedule="0 */6 * * * *",   # cada 6 minutos
    arg_name="timer",
    run_on_startup=True          # ejecutar al hacer deploy para verificar
)
def gdacs_detector(timer: func.TimerRequest) -> None:
    """
    Punto de entrada Azure Functions.
    1. Consulta las 4 fuentes meteorológicas.
    2. Determina nivel consolidado VERDE/AMARILLO/NARANJA/ROJO.
    3. Publica en Service Bus topic 'alert-events' si nivel >= AMARILLO.
    """
    logging.info("fn-gdacs-detector: iniciando ciclo de detección")

    # ── 1. Consultar fuentes ────────────────────────────────────────────────
    ciclones_nhc  = consultar_nhc()
    alertas_gdacs = consultar_gdacs()
    pronostico    = consultar_ecmwf()
    nivel_mar     = consultar_coops()

    # ── 2. Nivel consolidado ────────────────────────────────────────────────
    alerta_consolidada = "verde"

    if ciclones_nhc:
        mas_cercano = min(ciclones_nhc, key=lambda x: x["distancia_km"])
        alerta_consolidada = mas_cercano["nivel_alerta"]
    elif alertas_gdacs:
        nivel_g = alertas_gdacs[0]["nivel_gdacs"].lower()
        if nivel_g == "red":
            alerta_consolidada = "rojo"
        elif nivel_g == "orange":
            alerta_consolidada = "naranja"
    
    if alerta_consolidada == "verde" and pronostico:
        for isla, datos in pronostico.items():
            if datos and datos.get("alerta_viento"):
                alerta_consolidada = "amarillo"
                break

    logging.info(f"fn-gdacs-detector: nivel consolidado = {alerta_consolidada.upper()}")

    # ── 3. Publicar en Service Bus si nivel >= AMARILLO ─────────────────────
    if alerta_consolidada in ("amarillo", "naranja", "rojo"):
        mensaje = {
            "nivel_alerta":    alerta_consolidada,
            "ciclones_nhc":    ciclones_nhc,
            "alertas_gdacs":   alertas_gdacs,
            "ecmwf":           pronostico,
            "nivel_mar_coops": nivel_mar,
            "version":         "1.0.0"
        }
        _publicar_service_bus(mensaje)
        logging.info(f"fn-gdacs-detector: evento publicado en alert-events")
    else:
        logging.info("fn-gdacs-detector: nivel VERDE — sin publicación")


def _publicar_service_bus(payload: dict) -> None:
    """Publica el payload en el topic alert-events del Service Bus."""
    conn_str = os.environ["SERVICE_BUS_CONNECTION"]
    with ServiceBusClient.from_connection_string(conn_str) as client:
        with client.get_topic_sender(topic_name="alert-events") as sender:
            mensaje = ServiceBusMessage(
                body=json.dumps(payload, default=str),
                content_type="application/json"
            )
            sender.send_messages(mensaje)
