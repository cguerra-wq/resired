import azure.functions as func
import logging
import json
import os
from azure.servicebus import ServiceBusClient, ServiceBusMessage

from functions.gdacs_detector.parse_storms import (
    consultar_nhc,
    consultar_gdacs,
    consultar_ecmwf,
    consultar_coops,
)

app = func.FunctionApp()

@app.timer_trigger(
    schedule="0 */6 * * * *",
    arg_name="timer",
    run_on_startup=True
)
def gdacs_detector(timer: func.TimerRequest) -> None:
    """Detecta amenazas meteorológicas cada 6 minutos."""
    logging.info("fn-gdacs-detector: iniciando ciclo de detección")

    ciclones_nhc  = consultar_nhc()
    alertas_gdacs = consultar_gdacs()
    pronostico    = consultar_ecmwf()
    nivel_mar     = consultar_coops()

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

    if alerta_consolidada in ("amarillo", "naranja", "rojo"):
        conn_str = os.environ["SERVICE_BUS_CONNECTION"]
        with ServiceBusClient.from_connection_string(conn_str) as client:
            with client.get_topic_sender(topic_name="alert-events") as sender:
                mensaje = ServiceBusMessage(
                    body=json.dumps({
                        "nivel_alerta":     alerta_consolidada,
                        "ciclones_nhc":     ciclones_nhc,
                        "alertas_gdacs":    alertas_gdacs,
                        "ecmwf":            pronostico,
                        "nivel_mar_coops":  nivel_mar,
                        "version":          "1.0.0"
                    }, default=str),
                    content_type="application/json"
                )
                sender.send_messages(mensaje)
        logging.info("fn-gdacs-detector: evento publicado en alert-events")
    else:
        logging.info("fn-gdacs-detector: nivel VERDE — sin publicación")