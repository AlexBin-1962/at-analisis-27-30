import json
import re
from pathlib import Path

# Carpeta base = un nivel arriba de /scripts (o sea, /estrategico)
BASE_DIR = Path(__file__).resolve().parent.parent

IN_PATH = BASE_DIR / "data" / "casillas" / "casillas_min_por_seccion.json"
OUT_JSON_ENRIQUECIDO = BASE_DIR / "data" / "casillas" / "casillas_min_por_seccion_enriquecido.json"
OUT_GEOJSON = BASE_DIR / "data" / "casillas" / "casillas_geo_sin_coords.geojson"



def limpiar_domicilio(raw: str) -> str:
    """Normaliza una copia del domicilio para geocodificar mejor."""
    if not raw:
        return ""

    txt = str(raw).upper().strip()

    # Quitar "DOMICILIO:" al inicio solo en la copia
    txt = re.sub(r"^DOMICILIO\s*:\s*", "", txt)

    # Reemplazar múltiples espacios por uno
    txt = re.sub(r"\s+", " ", txt)

    # Normalizar abreviaturas comunes
    reemplazos = {
        " NO. ": " ",
        " NUM. ": " ",
        " NUMERO ": " ",
        " NÚM. ": " ",
        " S/N": " SN",
        "C/": "CALLE ",
        " C. ": " CALLE ",
    }
    for k, v in reemplazos.items():
        txt = txt.replace(k, v)

    txt = txt.strip(",.;- ")

    return txt


def domicilio_corto(txt: str) -> str:
    """
    Genera DOMICILIO_CORTO a partir de DOMICILIO_LIMPIO:
    normalmente calle + número, cortando antes de COL., FRACC., BARRIO, etc.
    """
    if not txt:
        return ""

    base = " " + txt + " "

    marcadores = [
        " COLONIA ",
        " COL. ",
        " FRACCIONAMIENTO ",
        " FRACC. ",
        " BARRIO ",
        " ZONA ",
        " COMUNIDAD ",
        " COL ",
        " FRACC ",
    ]

    corte_pos = len(base)
    for mk in marcadores:
        idx = base.find(mk)
        if idx != -1 and idx < corte_pos:
            corte_pos = idx

    corto = base[:corte_pos].strip()
    corto = corto.strip(",.;- ")

    return corto


def main():
    if not IN_PATH.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {IN_PATH}")

    with IN_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    data_enriquecido = []
    features = []

    for row in data:
        seccion = str(row.get("SECCION", "")).strip()
        casillas = row.get("casillas") or []

        nuevas_casillas = []

        for cas in casillas:
            dom_original = cas.get("DOMICILIO", "") or ""
            dom_limpio = limpiar_domicilio(dom_original)
            dom_corto = domicilio_corto(dom_limpio)

            # 👉 NO tocamos DOMICILIO, solo agregamos campos nuevos
            cas2 = dict(cas)
            cas2["DOMICILIO_LIMPIO"] = dom_limpio
            cas2["DOMICILIO_CORTO"] = dom_corto

            nuevas_casillas.append(cas2)

            casilla_id = (
                cas2.get("CLAVE")
                or cas2.get("CASILLA")
                or cas2.get("ID")
                or ""
            )

            feature = {
                "type": "Feature",
                "geometry": None,  # luego se llena con lat/lng
                "properties": {
                    "SECCION": seccion,
                    "CASILLA_ID": casilla_id,
                    "TIPO": cas2.get("TIPO", ""),
                    # Guardamos todo por si lo necesitamos:
                    "DOMICILIO": dom_original,        # tal cual
                    "DOMICILIO_LIMPIO": dom_limpio,   # copia normalizada
                    "DOMICILIO_CORTO": dom_corto,     # para geocodificar
                },
            }
            features.append(feature)

        new_row = dict(row)
        new_row["casillas"] = nuevas_casillas
        data_enriquecido.append(new_row)

    # JSON enriquecido (misma estructura, con campos nuevos)
    OUT_JSON_ENRIQUECIDO.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSON_ENRIQUECIDO.open("w", encoding="utf-8") as f:
        json.dump(data_enriquecido, f, ensure_ascii=False, indent=2)

    # GeoJSON esqueleto para geocodificar
    geojson = {"type": "FeatureCollection", "features": features}
    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    with OUT_GEOJSON.open("w", encoding="utf-8") as f:
        json.dump(geojson, f, ensure_ascii=False, indent=2)

    print("✔ Listo:")
    print(f"  - JSON enriquecido: {OUT_JSON_ENRIQUECIDO}")
    print(f"  - GeoJSON para geocodificar: {OUT_GEOJSON}")


if __name__ == "__main__":
    main()
