#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
geocodificar_casillas_leon_v2.py

Lee ubi_casillas_direcciones.csv (SECCION, CASILLA, LOCALIDAD, DOMICILIO),
limpia los domicilios, construye DOMICILIO_LIMPIO y DOMICILIO_CORTO,
geocodifica pensando en León de los Aldama, Guanajuato
y genera puntos_casillas_leon.geojson.

Requisitos:
  pip install geopy
"""

import csv
import json
import time
import unicodedata
from pathlib import Path

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter

# === RUTAS (ajusta si lo necesitas) =====================

BASE_DIR = Path(__file__).resolve().parents[1]  # carpeta estrategico/
DATA_DIR = BASE_DIR / "data" / "casillas"

CSV_IN         = DATA_DIR / "ubi_casillas_direcciones.csv"
GEOJSON_OUT    = DATA_DIR / "puntos_casillas_leon.geojson"
MUNI_MAP_CSV   = DATA_DIR / "secciones_municipio.csv"


# === UTILIDADES DE TEXTO =================================

def strip_accents_keep_enie(text: str) -> str:
    """
    Quita acentos PERO conserva la Ñ.
    Internamente marca ñ/Ñ con tokens, quita acentos y luego los devuelve.
    """
    if not text:
        return ""

    # Normalizamos espacios
    text = " ".join(text.split())

    # Marcamos ñ/Ñ
    text = text.replace("ñ", "__enie_min__")
    text = text.replace("Ñ", "__enie_may__")

    # Quitamos acentos del resto
    normalized = unicodedata.normalize("NFD", text)
    without_marks = "".join(
        ch for ch in normalized
        if unicodedata.category(ch) != "Mn"
    )

    # Devolvemos Ñ
    without_marks = without_marks.replace("__enie_min__", "ñ")
    without_marks = without_marks.replace("__enie_may__", "Ñ")

    return without_marks


def limpiar_frases_basura(domicilio: str) -> str:
    """
    Elimina o recorta frases que no ayudan al geocoder:
    'A 50 METROS DE...', 'FRENTE A...', 'ENTRE CALLE...', etc.
    Mantiene la parte más estructurada del domicilio.
    """
    if not domicilio:
        return ""

    txt = domicilio.upper()

    # Cortar a partir de expresiones que agregan ruido
    cortes = [
        " A 50 METROS",
        " A 100 METROS",
        " A 200 METROS",
        " A UN COSTADO",
        " FRENTE A ",
        " FRENTE AL ",
        " ENTRE CALLE",
        " ENTRE LA CALLE",
        " ESQUINA ",
        " ESQ. ",
        " ESQ ",
        " SOBRE LA CARRETERA",
        " SOBRE CARRETERA",
        " LADO DERECHO",
        " LADO IZQUIERDO",
        " A ESPALDAS",
    ]

    for marca in cortes:
        idx = txt.find(marca)
        if idx != -1:
            txt = txt[:idx]
            break

    # Quitamos 'SIN NUMERO', etc.
    txt = txt.replace(" SIN NUMERO", "")
    txt = txt.replace(" S/N", "")

    # Normalizamos espacios
    txt = " ".join(txt.split())

    return txt.strip(", ")


def construir_domicilio_corto(domicilio_limpio: str,
                              localidad: str | None) -> str:
    """
    Construye DOMICILIO_CORTO usando principalmente:
      - nombre del inmueble + calle + numero (lo que venga en DOMICILIO_LIMPIO)
      - localidad/colonia (si ayuda)
    No agrega municipio ni país; eso se suma en la query de geocodificación.
    """
    partes = []

    if domicilio_limpio:
        partes.append(domicilio_limpio)

    # Si la localidad no viene ya dentro del texto, la agregamos
    loc = (localidad or "").strip()
    if loc and loc.upper() not in domicilio_limpio.upper():
        partes.append(loc)

    return ", ".join(partes)


def armar_queries_geocod(domicilio_corto: str,
                         localidad: str | None,
                         municipio: str | None) -> list[str]:
    """
    Genera una lista de queries, ahora sí con MUNICIPIO real.
    """
    queries = []

    loc = (localidad or "").strip()
    muni = (municipio or "").strip()

    # 1) Domicilio corto + municipio + estado
    if domicilio_corto and muni:
        q1 = f"{domicilio_corto}, {muni}, Guanajuato, Mexico"
        queries.append(q1)
    elif domicilio_corto:
        q1 = f"{domicilio_corto}, Guanajuato, Mexico"
        queries.append(q1)

    # 2) Localidad + municipio + estado
    if loc and muni:
        q2 = f"{loc}, {muni}, Guanajuato, Mexico"
        queries.append(q2)
    elif loc:
        q2 = f"{loc}, Guanajuato, Mexico"
        queries.append(q2)

    # 3) Fallback súper general
    if muni:
        q3 = f"{muni}, Guanajuato, Mexico"
        queries.append(q3)
    queries.append("Guanajuato, Mexico")

    # Normalizamos acentos pero conservamos Ñ
    queries_norm = [strip_accents_keep_enie(q) for q in queries]

    # Quitamos duplicados preservando orden
    seen = set()
    unique = []
    for q in queries_norm:
        if q not in seen:
            seen.add(q)
            unique.append(q)

    return unique




# === PROCESO PRINCIPAL ====================================

def cargar_mapa_seccion_municipio(path: Path) -> dict[str, str]:
    """
    Lee un CSV con columnas SECCION y MUNICIPIO,
    y regresa un dict {seccion: municipio}.
    """
    mapping = {}
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sec = (row.get("SECCION") or "").strip()
            mun = (row.get("MUNICIPIO") or "").strip()
            if sec and mun:
                # opcional: rellenar con ceros a 4 dígitos si aplica
                mapping[sec] = mun
    return mapping


def main():

    if not MUNI_MAP_CSV.exists():
        raise FileNotFoundError(f"No se encontró el mapa seccion→municipio: {MUNI_MAP_CSV}")

    mapa_muni = cargar_mapa_seccion_municipio(MUNI_MAP_CSV)
    print(f"Mapa seccion→municipio cargado con {len(mapa_muni)} entradas.")


    if not CSV_IN.exists():
        raise FileNotFoundError(f"No se encontró el CSV de entrada: {CSV_IN}")

    print(f"Leyendo CSV: {CSV_IN}")

    # Geocoder
    geolocator = Nominatim(user_agent="AT-27-30-DiaD-Leon", timeout=15)
    geocode = RateLimiter(geolocator.geocode,
                          min_delay_seconds=1.2,
                          max_retries=2,
                          error_wait_seconds=3.0)

    features = []
    ok_count = 0
    fail_count = 0

    with CSV_IN.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter=",")
        rows = list(reader)

    total_rows = len(rows)
    print(f"Total de filas en CSV: {total_rows}")

    for idx, row in enumerate(rows, start=1):
        seccion   = (row.get("SECCION")  or "").strip()
        casilla   = (row.get("CASILLA")  or "").strip()
        localidad = (row.get("LOCALIDAD") or "").strip()
        domicilio_original = (row.get("DOMICILIO") or "").strip()

        municipio = mapa_muni.get(seccion, "")

        # Domicilio limpio y corto
        dom_limpio = limpiar_frases_basura(domicilio_original)
        dom_corto  = construir_domicilio_corto(dom_limpio, localidad)

        # Preparamos GeoJSON base
        props = {
            "SECCION": seccion,
            "CASILLA_ID": casilla,
            "LOCALIDAD": localidad,
            "DOMICILIO": domicilio_original,
            "DOMICILIO_LIMPIO": dom_limpio,
            "DOMICILIO_CORTO": dom_corto,
        }

        geometry = None
        geocod_status = "SIN_MATCH"
        geocod_query = ""

        # Solo procesamos si hay algo de domicilio / localidad
        queries = armar_queries_geocod(dom_corto, localidad, municipio)


        for q in queries:
            if not q:
                continue
            try:
                loc = geocode(q)
            except Exception as e:
                print(f"[{idx}] ERROR geocodificando: {q} → {e}")
                time.sleep(0.5)
                continue

            if loc:
                geocod_status = "OK"
                geocod_query = q
                geometry = {
                    "type": "Point",
                    "coordinates": [loc.longitude, loc.latitude]
                }
                ok_count += 1
                print(f"[{idx}] OK  Sec {seccion} Casilla {casilla} → {loc.latitude:.6f}, {loc.longitude:.6f}")
                break
            else:
                geocod_query = q  # guardamos el último intentado

        if geocod_status != "OK":
            fail_count += 1
            print(f"[{idx}] FAIL Sec {seccion} Casilla {casilla} → '{geocod_query}'")

        props["GEOCOD_STATUS"] = geocod_status
        props["GEOCOD_QUERY"]  = geocod_query

        feature = {
            "type": "Feature",
            "geometry": geometry,
            "properties": props
        }
        features.append(feature)

        # Respiro ligero
        time.sleep(0.2)

    # Construimos el FeatureCollection
    fc = {
        "type": "FeatureCollection",
        "features": features
    }

    GEOJSON_OUT.parent.mkdir(parents=True, exist_ok=True)
    with GEOJSON_OUT.open("w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=2)

    print("\n✅ Geocodificación León terminada.")
    print(f"   Casillas OK:   {ok_count}")
    print(f"   Casillas FAIL: {fail_count}")
    print(f"   Archivo GeoJSON: {GEOJSON_OUT}")


if __name__ == "__main__":
    main()
