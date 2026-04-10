import azure.functions as func
import logging
import json
import os
import requests
from azure.servicebus import ServiceBusClient, ServiceBusMessage

app = func.FunctionApp()

def consultar_nhc() -> list:
    try:
        r = requests.get(
            "https://www.nhc.noaa.gov/CurrentStorms.json", timeout=10
        )
        data = r.json()
        ciclones = []
        for storm in data.get("activeStorms", []):
            basin = storm.get("basin", "")
            if basin in ("al", "ep"):
                ciclones.append({
                    "id":           storm.get("id"),
                    "nombre":       storm.get("name"),
                    "basin":        basin,
                    "nivel_alerta": "naranja",
                    "distancia_km": 9999,
                })
        return ciclones
    except Exception as e:
        logging.warning(f"consultar_nhc error: {e}")
        return []

def consultar_gdacs() -> list:
    try:
        import feedparser
        feed = feedparser.parse("https://www.gdacs.org/xml/rss.xml")
        alertas = []
        for entry in feed.get("entries", []):
            gdacs_type = entry.get("gdacs_eventtype", "")
            if gdacs_type == "TC":
                alertas.append({
                    "titulo":      entry.get("title"),
                    "nivel_gdacs": entry.get("gdacs_alertlevel", "Green"),
                    "pais":        entry.get("gdacs_country", ""),
                })
        return alertas
    except Exception as e:
        logging.warning(f"consultar_gdacs error: {e}")
        return []

def consultar_ecmwf() -> dict:
    try:
        islas = {
            "san_andres":   {"lat": 12.5, "lon": -81.7},
            "providencia":  {"lat": 13.3, "lon": -81.4},
        }
        pronostico = {}
        for isla, coords in islas.items():
            url = (
                f"https://api.open-meteo.com/v1/forecast"
                f"?latitude={coords['lat']}&longitude={coords['lon']}"
                f"&hourly=windspeed_10m&forecast_days=3&timezone=auto"
            )
            r = requests.get(url, timeout=10)
            data = r.json()
            vientos = data.get("hourly", {}).get("windspeed_10m", [])
            max_viento = max(vientos[:72]) if vientos else 0
            pronostico[isla] = {
                "max_viento_kmh": max_viento,
                "alerta_viento":  max_viento > 62,
            }
        return pronostico
    except Exception as e:
        logging.warning(f"consultar_ecmwf error: {e}")
        return {}

def consultar_coops() -> dict:
    try:
        url = (
            "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
            "?station=9755371&product=water_level&datum=MLLW"
            "&time_zone=GMT&units=metric&format=json&range=6"
        )
        r = requests.get(url, timeout=10)
        data = r.json()
        lecturas = data.get("data", [])
        if lecturas:
            nivel = float(lecturas[-1].get("v", 0))
            return {"nivel_m": nivel, "alerta_marea": nivel > 0.5}
        return {"nivel_m": 0, "alerta_marea": False}
    except Exception as e:
        logging.warning(f"consultar_coops error: {e}")
        return {}

def _publicar_service_bus(payload: dict) -> None:
    conn_str = os.environ["SERVICE_BUS_CONNECTION"]
    with ServiceBusClient.from_connection_string(conn_str) as client:
        with client.get_topic_sender(topic_name="alert-events") as sender:
            mensaje = ServiceBusMessage(
                body=json.dumps(payload, default=str),
                content_type="application/json"
            )
            sender.send_messages(mensaje)

@app.timer_trigger(
    schedule="0 */6 * * * *",
    arg_name="timer",
    run_on_startup=True
)
def gdacs_detector(timer: func.TimerRequest) -> None:
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

    logging.info(
        f"fn-gdacs-detector: nivel consolidado = {alerta_consolidada.upper()}"
    )

    if alerta_consolidada in ("amarillo", "naranja", "rojo"):
        payload = {
            "nivel_alerta":    alerta_consolidada,
            "ciclones_nhc":    ciclones_nhc,
            "alertas_gdacs":   alertas_gdacs,
            "ecmwf":           pronostico,
            "nivel_mar_coops": nivel_mar,
            "version":         "1.0.0"
        }
        _publicar_service_bus(payload)
        logging.info("fn-gdacs-detector: evento publicado en alert-events")
    else:
        logging.info("fn-gdacs-detector: nivel VERDE — sin publicación")