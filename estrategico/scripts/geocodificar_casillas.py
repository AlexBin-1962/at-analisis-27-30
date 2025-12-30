import json
import time
import re
from pathlib import Path

from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter


# === RUTAS ===
BASE_DIR = Path(__file__).resolve().parent.parent
IN_GEOJSON = BASE_DIR / "data" / "casillas" / "casillas_geo_sin_coords.geojson"
OUT_GEOJSON = BASE_DIR / "data" / "casillas" / "casillas_geo_geocodificadas.geojson"


def extraer_cp_y_mpio(dom_full: str):
  """
  Intenta extraer CP y municipio de un domicilio tipo:
  ... , 36970, ABASOLO, GUANAJUATO, ...
  """
  if not dom_full:
    return None, None

  txt = dom_full.upper()
  m = re.search(r",\s*(\d{5}),\s*([^,]+),\s*GUANAJUATO", txt)
  if m:
    cp = m.group(1)
    mpio = m.group(2).title()
    return cp, mpio
  return None, None

LOCALIDAD_CORR = {
        "ESTACIÓN JOAQUÓN": "Estación Joaquín",
        "SAN JOS DE GONZΜLEZ": "San José de González",
        "ALTO DE ALCOCER": "Alto de Alcocer",  # quizá ya esté bien; lo dejamos igual por si luego cambiamos
  }


def extraer_localidad(dom_full: str):
    if not dom_full:
        return None

    txt = dom_full.upper()

    m = re.search(r"LOCALIDAD\s+([^,]+)", txt)
    if m:
        loc = m.group(1).strip().upper()
    else:
        m2 = re.search(r",\s*([^,]+),\s*(\d{5}),\s*ABASOLO", txt)
        if not m2:
            return None
        loc = m2.group(1).strip().upper()

    # 🔧 Correcciones específicas
    loc_corr = LOCALIDAD_CORR.get(loc, loc)

    return loc_corr.title()




def build_query(props: dict):
    """
    Construye una query amigable para Nominatim.
    - Para zonas rurales: usa LOCALIDAD + municipio + estado + país.
    - Para lo urbano (donde luego afinemos): podríamos usar calle + número.
    """
    dom_corto = props.get("DOMICILIO_CORTO") or ""
    dom_limpio = props.get("DOMICILIO_LIMPIO") or ""
    dom_full = props.get("DOMICILIO") or ""

    if not dom_corto and not dom_limpio and not dom_full:
        return None

    # Extraemos CP y municipio (mpio)
    cp, mpio = extraer_cp_y_mpio(dom_full)
    localidad = extraer_localidad(dom_full)

    # 🔹 PRIORIDAD 1: LOCALIDAD + MPIO (rural)
    if localidad and mpio:
        return f"{localidad}, {mpio}, Guanajuato, México"

    # 🔹 PRIORIDAD 2: solo municipio
    if mpio:
        return f"{mpio}, Guanajuato, México"

    # 🔹 PRIORIDAD 3 (respaldo): domicilio corto + estado + país
    base = dom_corto or dom_limpio or dom_full
    return f"{base}, Guanajuato, México"



def main():
  if not IN_GEOJSON.exists():
    raise FileNotFoundError(f"No se encontró el archivo de entrada: {IN_GEOJSON}")

  with IN_GEOJSON.open("r", encoding="utf-8") as f:
    data = json.load(f)

  features = data.get("features", [])
  print(f"🔎 Geocodificando {len(features)} casillas…")

  geolocator = Nominatim(user_agent="AT2730-DiaD-Geocoder", timeout=20)
  geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.2, max_retries=2, error_wait_seconds=3.0)

  cache = {}
  ok = 0
  fail = 0

  for i, feat in enumerate(features, start=1):
    props = feat.get("properties", {})
    sec = props.get("SECCION")
    cid = props.get("CASILLA_ID")

    q = build_query(props)
    if not q:
      props["GEOCOD_STATUS"] = "SIN_DIRECCION"
      feat["geometry"] = None
      fail += 1
      continue

    if q in cache:
      loc = cache[q]
    else:
      try:
        loc = geocode(q)
      except Exception as e:
        print(f"[{i}] Error geocodificando '{q}': {e}")
        loc = None
      cache[q] = loc

    if loc:
      lon = loc.longitude
      lat = loc.latitude
      feat["geometry"] = {
        "type": "Point",
        "coordinates": [lon, lat]
      }
      props["GEOCOD_STATUS"] = "OK"
      props["GEOCOD_QUERY"] = q
      ok += 1
      print(f"[{i}] OK  Sec {sec} Casilla {cid} → {lat:.6f}, {lon:.6f}")
    else:
      feat["geometry"] = None
      props["GEOCOD_STATUS"] = "SIN_MATCH"
      props["GEOCOD_QUERY"] = q
      fail += 1
      print(f"[{i}] FAIL Sec {sec} Casilla {cid} → '{q}'")

    # Pequeña pausa extra por si acaso (RateLimiter ya mete otra)
    time.sleep(0.1)

  data["features"] = features

  OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
  with OUT_GEOJSON.open("w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

  print("✅ Geocodificación terminada.")
  print(f"   Casillas OK:   {ok}")
  print(f"   Casillas FAIL: {fail}")
  print(f"   Archivo salida: {OUT_GEOJSON}")


if __name__ == "__main__":
  main()
