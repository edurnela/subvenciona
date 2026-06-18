#!/usr/bin/env python3
"""
fetch_data.py — Descarga convocatorias de subvenciones desde la API oficial de la BDNS
(Base de Datos Nacional de Subvenciones) y genera un JSON limpio para el directorio.

API oficial (sin autenticación):
    Base: https://www.infosubvenciones.es/bdnstrans/api
    Espejo: https://www.pap.hacienda.gob.es/bdnstrans/api

⚠️ Importante (verificado contra la API real, junio 2026):
El endpoint de búsqueda `/convocatorias/busqueda` solo devuelve un ÍNDICE ligero
(título, organismo por niveles, fecha de recepción). NO trae importe, plazos, sector,
beneficiarios ni si está abierta. Esos datos — los más importantes para el directorio —
solo están en el endpoint de DETALLE por convocatoria:

    GET /convocatorias?vpd=GE&numConv=<numeroConvocatoria>

Por eso el fetch es en dos fases:
  1) Listar las convocatorias más recientes (índice paginado).
  2) Enriquecer cada una con su detalle (en paralelo, con cortesía).

Uso:
    python fetch_data.py --solo-abiertas --paginas 3
    python fetch_data.py --paginas 5 --page-size 200 --workers 8
    python fetch_data.py --descripcion "digitalización"
"""

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Falta 'requests'. Ejecuta: pip install -r requirements.txt")

# Espejos oficiales; si uno falla, probamos el siguiente.
BASES = [
    "https://www.infosubvenciones.es/bdnstrans/api",
    "https://www.pap.hacienda.gob.es/bdnstrans/api",
]
EP_BUSQUEDA = "/convocatorias/busqueda"
EP_DETALLE = "/convocatorias"
VPD = "GE"  # portal general — obligatorio en la mayoría de llamadas

DATA_DIR = Path(__file__).parent / "data"
OUT_FILE = DATA_DIR / "convocatorias.json"
RAW_FILE = DATA_DIR / "raw_sample.json"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "subvenciona-directorio/1.0 (+https://github.com)",
}

# Mapa código NUTS (regiones[].descripcion empieza por "ESxx - ...") → CCAA limpia.
NUTS_CCAA = {
    "ES11": "Galicia", "ES12": "Asturias", "ES13": "Cantabria",
    "ES21": "País Vasco", "ES22": "Navarra", "ES23": "La Rioja", "ES24": "Aragón",
    "ES30": "Madrid", "ES41": "Castilla y León", "ES42": "Castilla-La Mancha",
    "ES43": "Extremadura", "ES51": "Cataluña", "ES52": "Comunidad Valenciana",
    "ES53": "Islas Baleares", "ES61": "Andalucía", "ES62": "Murcia",
    "ES63": "Ceuta", "ES64": "Melilla", "ES70": "Canarias",
}
# Por si solo viene el código de nivel-1 NUTS (ES1, ES2…) o nivel-2 nombre.
NIVEL2_CCAA = {
    "GALICIA": "Galicia", "PRINCIPADO DE ASTURIAS": "Asturias", "ASTURIAS": "Asturias",
    "CANTABRIA": "Cantabria", "PAIS VASCO": "País Vasco", "PAÍS VASCO": "País Vasco",
    "COMUNIDAD FORAL DE NAVARRA": "Navarra", "NAVARRA": "Navarra",
    "LA RIOJA": "La Rioja", "ARAGON": "Aragón", "ARAGÓN": "Aragón",
    "COMUNIDAD DE MADRID": "Madrid", "MADRID": "Madrid",
    "CASTILLA Y LEON": "Castilla y León", "CASTILLA Y LEÓN": "Castilla y León",
    "CASTILLA-LA MANCHA": "Castilla-La Mancha", "CASTILLA LA MANCHA": "Castilla-La Mancha",
    "EXTREMADURA": "Extremadura", "CATALUÑA": "Cataluña", "CATALUNYA": "Cataluña",
    "COMUNITAT VALENCIANA": "Comunidad Valenciana", "COMUNIDAD VALENCIANA": "Comunidad Valenciana",
    "ILLES BALEARS": "Islas Baleares", "ISLAS BALEARES": "Islas Baleares",
    "ANDALUCIA": "Andalucía", "ANDALUCÍA": "Andalucía",
    "REGION DE MURCIA": "Murcia", "REGIÓN DE MURCIA": "Murcia", "MURCIA": "Murcia",
    "CEUTA": "Ceuta", "MELILLA": "Melilla", "CANARIAS": "Canarias",
}

# Palabras que se mantienen en minúscula al "titular" texto en MAYÚSCULAS.
MINUSCULAS = {"de", "del", "la", "las", "el", "los", "y", "e", "o", "u",
              "a", "en", "para", "por", "con", "the", "of"}


def primero(d, *claves, default=None):
    """Devuelve el primer valor no vacío entre varias claves posibles (mapeo defensivo)."""
    for k in claves:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return default


def titular(texto):
    """Convierte 'CONSEJERÍA DE SALUD' → 'Consejería de Salud' (legibilidad)."""
    if not texto:
        return ""
    texto = str(texto).strip()
    # Si ya tiene minúsculas, lo dejamos como viene.
    if texto != texto.upper():
        return texto
    palabras = texto.lower().split()
    out = []
    for i, w in enumerate(palabras):
        if i > 0 and w in MINUSCULAS:
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def lista_descripciones(valor, maximo=3):
    """[{'descripcion': 'X'}, …] → 'X, Y' (texto legible y corto)."""
    if not isinstance(valor, list):
        return ""
    descs = []
    for it in valor:
        d = it.get("descripcion") if isinstance(it, dict) else it
        if d:
            d = titular(str(d).strip())
            if d not in descs:
                descs.append(d)
    return ", ".join(descs[:maximo])


def deriva_region(detalle):
    """Devuelve una CCAA limpia a partir de regiones[] / niveles del órgano."""
    organo = detalle.get("organo") or {}
    nivel1 = (organo.get("nivel1") or detalle.get("nivel1") or "").upper()

    # 1) Estatal → toda España
    if nivel1 == "ESTATAL":
        return "Toda España"

    # 2) regiones[].descripcion: "ES12 - PRINCIPADO DE ASTURIAS" / "ES7 - CANARIAS" / "ES - ESPAÑA"
    regiones = detalle.get("regiones") or []
    ccaas = set()
    nacional = False
    for r in regiones:
        desc = (r.get("descripcion") if isinstance(r, dict) else str(r)) or ""
        partes = desc.split(" - ", 1)
        cod = partes[0].strip().upper()
        nombre = (partes[1] if len(partes) > 1 else "").strip().upper()
        if "ESPAÑA" in nombre or cod == "ES":
            nacional = True
        elif cod in NUTS_CCAA:
            ccaas.add(NUTS_CCAA[cod])
        elif cod[:4] in NUTS_CCAA:
            ccaas.add(NUTS_CCAA[cod[:4]])
        elif nombre in NIVEL2_CCAA:          # el nombre tras el guion suele bastar
            ccaas.add(NIVEL2_CCAA[nombre])
    if len(ccaas) == 1:
        return next(iter(ccaas))
    if len(ccaas) > 1:
        return "Varias comunidades"
    if nacional:
        return "Toda España"

    # 3) Derivar del nivel2 del órgano (autonómica / local con CCAA en el nombre)
    nivel2 = (organo.get("nivel2") or detalle.get("nivel2") or "").upper().strip()
    if nivel2 in NIVEL2_CCAA:
        return NIVEL2_CCAA[nivel2]

    return ""


def es_competitiva(detalle):
    """True si es concurrencia competitiva (solicitable), no concesión directa/nominativa."""
    return "concurrencia competitiva" in (detalle.get("tipoConvocatoria") or "").lower()


def es_para_actividad_economica(detalle):
    """True si algún tipo de beneficiario desarrolla actividad económica (pyme, autónomo, empresa).

    Excluye las dirigidas solo a 'personas físicas/jurídicas que NO desarrollan actividad
    económica' (asociaciones, fundaciones, particulares): no sirven para autónomos ni pymes.
    """
    for tb in (detalle.get("tiposBeneficiarios") or []):
        d = (tb.get("descripcion") if isinstance(tb, dict) else str(tb) or "").upper()
        if "NO DESARROLLAN" in d:
            continue
        if "ACTIVIDAD ECONÓMICA" in d or "ACTIVIDAD ECONOMICA" in d:
            return True
        if any(p in d for p in ("EMPRESA", "PYME", "AUTÓNOMO", "AUTONOMO")):
            return True
    return False


import re
import unicodedata

# Marcadores que indican que una convocatoria se ha partido en líneas/lotes/modalidades.
_SPLIT = re.compile(
    r"\b(linea|lineas|lote|lotes|modalidad|modalidades|anexo|apartado|programa)\b"
    r"|\b\d+\s?[a-z]?\)"
)


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # quita acentos
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def clave_grupo(titulo, organo, fecha_fin):
    """Clave de 'convocatoria matriz': mismas líneas de una convocatoria comparten clave.

    Combina organismo + prefijo del título (cortado en el primer marcador de línea/lote)
    + fecha de cierre. Convocatorias distintas del mismo organismo NO colapsan porque su
    prefijo de título difiere.
    """
    org = _norm(organo)
    t = _norm(titulo)
    m = _SPLIT.search(t)
    pref = t[:m.start()] if (m and m.start() > 15) else t
    pref = pref.strip()[:55]
    if len(pref) < 18:
        pref = t[:40]
    return f"{org}|{pref}|{fecha_fin or ''}"


def normaliza(detalle):
    """Convierte el DETALLE crudo de la BDNS a nuestro esquema estable."""
    organo_obj = detalle.get("organo") or {}
    org_txt = primero(organo_obj, "nivel3", "nivel2", "nivel1", default="") or \
        primero(detalle, "nivel3", "nivel2", "nivel1", default="")

    codigo = str(primero(detalle, "codigoBDNS", "numeroConvocatoria", "id", default=""))
    titulo = primero(detalle, "descripcion", "tituloConvocatoria", default="(sin título)")
    organo = titular(org_txt)
    fecha_fin = primero(detalle, "fechaFinSolicitud", default=None)

    return {
        "id": primero(detalle, "id", "codigoBDNS"),
        "codigo_bdns": codigo,
        "titulo": titulo,
        "organo": organo,
        "nivel_admin": titular(primero(organo_obj, "nivel1", default="") or detalle.get("nivel1", "")),
        "region": deriva_region(detalle),
        "importe": primero(detalle, "presupuestoTotal", "importeTotal", "importe", default=None),
        "fecha_inicio": primero(detalle, "fechaInicioSolicitud", "fechaRecepcion", default=None),
        "fecha_fin": fecha_fin,
        "abierta": detalle.get("abierto"),
        "sector": titular(primero(detalle, "descripcionFinalidad", default="")) or
                  lista_descripciones(detalle.get("sectores"), maximo=2),
        "beneficiarios": lista_descripciones(detalle.get("tiposBeneficiarios"), maximo=3),
        # Clasificación para distinguir lo realmente solicitable por autónomos/pymes:
        "tipo_convocatoria": detalle.get("tipoConvocatoria") or "",
        "competitiva": es_competitiva(detalle),       # concurrencia competitiva (no nominativa)
        "para_empresas": es_para_actividad_economica(detalle),  # beneficiario con actividad económica
        "grupo": clave_grupo(titulo, organo, fecha_fin),  # agrupa líneas de una misma convocatoria
        "url_oficial": _url_oficial(codigo),
        "bases_url": primero(detalle, "urlBasesReguladoras", "sedeElectronica", default=""),
    }


def colapsa_grupos(registros):
    """Colapsa las líneas de una misma convocatoria (mismo 'grupo') en una representante.

    Representante = la de mayor importe del grupo; se anota cuántas líneas más quedaron
    bajo `_extra` (el frontend muestra "+N líneas más de esta convocatoria"). Así el JSON
    diario ya viene sin las repeticiones que inundaban el listado.
    """
    grupos = {}
    for r in registros:
        k = r.get("grupo") or ("c" + str(r.get("codigo_bdns")))
        grupos.setdefault(k, []).append(r)
    salida = []
    for miembros in grupos.values():
        if len(miembros) == 1:
            salida.append(miembros[0])
            continue
        rep = dict(max(miembros, key=lambda r: r.get("importe") or 0))
        rep["_extra"] = len(miembros) - 1
        salida.append(rep)
    return salida


def _url_oficial(codigo):
    if not codigo:
        return ""
    return f"https://www.infosubvenciones.es/bdnstrans/GE/es/convocatoria/{codigo}"


def extrae_lista(payload):
    """La lista de registros del índice viene bajo 'content' (Spring Page)."""
    if isinstance(payload, list):
        return payload
    for k in ("content", "convocatorias", "data", "items", "results"):
        if isinstance(payload, dict) and isinstance(payload.get(k), list):
            return payload[k]
    return []


SESION = requests.Session()
SESION.headers.update(HEADERS)


def get_json(base, ep, params, timeout=30):
    r = SESION.get(base + ep, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_detalle(base, num, reintentos=4):
    """Trae el detalle de una convocatoria por su número, con reintentos.

    El servidor público limita las peticiones concurrentes (responde 429/5xx).
    Reintentamos con backoff incremental para no perder registros.
    """
    espera = 0.6
    for intento in range(reintentos):
        try:
            return get_json(base, EP_DETALLE, {"vpd": VPD, "numConv": num}, timeout=30)
        except Exception:
            if intento == reintentos - 1:
                return None
            time.sleep(espera)
            espera *= 1.8
    return None


def main():
    ap = argparse.ArgumentParser(description="Descarga convocatorias BDNS → data/convocatorias.json")
    ap.add_argument("--paginas", type=int, default=3, help="Páginas del índice a recorrer")
    ap.add_argument("--page-size", type=int, default=200, help="Registros por página del índice")
    ap.add_argument("--descripcion", default="", help="Filtro de texto opcional (busca en el índice)")
    ap.add_argument("--desde", default="", help="fechaDesde YYYY-MM-DD (por defecto este año)")
    ap.add_argument("--workers", type=int, default=2,
                    help="Descargas de detalle en paralelo (la API limita; 2 es lo seguro)")
    ap.add_argument("--solo-abiertas", action="store_true",
                    help="Conserva solo convocatorias con plazo de solicitud abierto hoy")
    ap.add_argument("--incluir-no-solicitables", action="store_true",
                    help="NO filtrar: incluye concesiones directas/nominativas y ayudas a entidades "
                         "sin actividad económica (por defecto se excluyen: directorio para autónomos/pymes)")
    ap.add_argument("--sin-colapsar", action="store_true",
                    help="NO colapsar las líneas de una misma convocatoria (por defecto se colapsan)")
    args = ap.parse_args()

    DATA_DIR.mkdir(exist_ok=True)
    # La API espera fechaDesde en formato DD/MM/YYYY (verificado).
    if args.desde:
        try:
            fecha_desde = datetime.strptime(args.desde, "%Y-%m-%d").strftime("%d/%m/%Y")
        except ValueError:
            fecha_desde = args.desde  # se asume que ya viene en DD/MM/YYYY
    else:
        fecha_desde = f"01/01/{date.today().year}"

    # Elegir el primer espejo que responda.
    base_ok = None
    for base in BASES:
        try:
            get_json(base, EP_BUSQUEDA, {"vpd": VPD, "page": 0, "pageSize": 1}, timeout=20)
            base_ok = base
            print(f"[ok] Usando API: {base}")
            break
        except Exception as e:
            print(f"[!] {base} no responde ({e}); probando siguiente espejo…")
    if not base_ok:
        sys.exit("No se pudo contactar con ningún espejo de la BDNS. Revisa tu conexión.")

    # ---- Fase 1: índice (las más recientes primero) ----
    numeros, raw_guardado = [], False
    for page in range(args.paginas):
        params = {"vpd": VPD, "page": page, "pageSize": args.page_size, "fechaDesde": fecha_desde}
        if args.descripcion:
            params["descripcion"] = args.descripcion
        try:
            payload = get_json(base_ok, EP_BUSQUEDA, params)
        except Exception as e:
            print(f"[!] Error en índice página {page}: {e}")
            break
        if not raw_guardado:
            RAW_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2)[:200000],
                                encoding="utf-8")
            raw_guardado = True
            print(f"[i] Volcado crudo del índice → {RAW_FILE.name}")
        lista = extrae_lista(payload)
        if not lista:
            print(f"[i] Índice página {page} sin registros; fin.")
            break
        for it in lista:
            n = primero(it, "numeroConvocatoria", "codigoBDNS", "id")
            if n:
                numeros.append(str(n))
        print(f"[ok] Índice página {page}: {len(lista)} (acumulado {len(numeros)})")
        time.sleep(0.3)

    # Deduplicar conservando orden (más recientes primero).
    vistos, orden = set(), []
    for n in numeros:
        if n not in vistos:
            vistos.add(n)
            orden.append(n)
    print(f"\n[i] {len(orden)} convocatorias únicas; trayendo detalle (workers={args.workers})…")

    # ---- Fase 2: detalle en paralelo ----
    registros = []
    hecho = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futuros = {ex.submit(fetch_detalle, base_ok, n): n for n in orden}
        for fut in as_completed(futuros):
            hecho += 1
            det = fut.result()
            if det:
                registros.append(normaliza(det))
            if hecho % 50 == 0 or hecho == len(orden):
                print(f"    detalle {hecho}/{len(orden)}")

    # Reordenar por código BDNS desc (proxy de "más reciente").
    registros.sort(key=lambda r: int(r["codigo_bdns"]) if r["codigo_bdns"].isdigit() else 0,
                   reverse=True)

    # Filtrar a lo realmente solicitable por autónomos/pymes (por defecto):
    # concurrencia competitiva (no nominativa) Y beneficiario con actividad económica.
    if not args.incluir_no_solicitables:
        brutos = len(registros)
        registros = [r for r in registros if r["competitiva"] and r["para_empresas"]]
        print(f"[i] Solicitables (competitiva + actividad económica): {len(registros)} de {brutos}")

    if args.solo_abiertas:
        hoy = date.today().isoformat()
        def abierta(r):
            if r.get("abierta") is True:
                return True
            ff = r.get("fecha_fin")
            fi = r.get("fecha_inicio")
            if not ff:
                return False
            if str(ff)[:10] < hoy:
                return False
            if fi and str(fi)[:10] > hoy:
                return False  # aún no ha empezado el plazo
            return True
        registros = [r for r in registros if abierta(r)]
        print(f"[i] Filtradas a abiertas: {len(registros)}")

    # Colapsar líneas de una misma convocatoria (por defecto) para que no inunden el listado.
    if not args.sin_colapsar:
        antes = len(registros)
        registros = colapsa_grupos(registros)
        registros.sort(key=lambda r: int(r["codigo_bdns"]) if str(r.get("codigo_bdns", "")).isdigit() else 0,
                       reverse=True)
        print(f"[i] Colapsadas líneas de una misma convocatoria: {antes} → {len(registros)}")

    salida = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "fuente": "BDNS — Base de Datos Nacional de Subvenciones (IGAE, Ministerio de Hacienda)",
        "total": len(registros),
        "convocatorias": registros,
    }
    OUT_FILE.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ {len(registros)} convocatorias → {OUT_FILE}")
    if not registros:
        print("⚠️  Vacío. Revisa data/raw_sample.json y ajusta normaliza().")


if __name__ == "__main__":
    main()
