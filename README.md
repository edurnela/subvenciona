# Subvenciona — Directorio de subvenciones para autónomos y pymes en España

Directorio buscable y filtrable de **convocatorias de subvenciones públicas abiertas** en España,
construido sobre la **API REST oficial de la BDNS** (Base de Datos Nacional de Subvenciones,
Ministerio de Hacienda — IGAE). Sin autenticación, datos oficiales, actualizados a diario.

> Por qué existe: el portal oficial (infosubvenciones.es) tiene datos de altísimo valor pero una
> búsqueda lenta y poco usable, enlaces que caducan y filtros pobres. Esto resuelve exactamente eso:
> "¿Qué puedo solicitar AHORA mismo según mi CCAA, mi sector y el importe?".

## Arquitectura (deliberadamente simple)

```
subvenciones-dir/
├── fetch_data.py        # Llama a la API oficial BDNS → genera data/convocatorias.json
├── data/
│   ├── convocatorias.json   # generado por fetch_data.py (no se versiona)
│   └── sample.json          # datos de muestra para que la web cargue sin fetch previo
├── index.html           # El directorio (frontend estático, sin build, sin dependencias)
├── requirements.txt
├── .gitignore
└── CLAUDE.md            # Contexto para Claude Code
```

No hay backend en producción: `fetch_data.py` genera un JSON estático y `index.html` lo consume.
Esto hace el despliegue trivial (GitHub Pages, Netlify, Vercel, Cloudflare Pages) y gratis.

## Fuente de datos — API oficial BDNS

- Base URL: `https://www.infosubvenciones.es/bdnstrans/api`
  (espejo: `https://www.pap.hacienda.gob.es/bdnstrans/api`)
- Sin API key. JSON. Parámetro `vpd=GE` (portal general) obligatorio.
- **El fetch es en dos fases** (verificado contra la API real, junio 2026):
  1. `GET /convocatorias/busqueda?vpd=GE&page=0&pageSize=200` — índice ligero, ordenado de más
     reciente a más antiguo. Solo trae título, organismo y fecha de recepción.
     `fechaDesde` debe ir en formato **DD/MM/YYYY**.
  2. `GET /convocatorias?vpd=GE&numConv=<n>` — **detalle** de cada convocatoria. Aquí están los
     datos que de verdad importan: `presupuestoTotal`, `fechaInicioSolicitud`/`fechaFinSolicitud`,
     `abierto`, `tiposBeneficiarios`, `sectores`, `descripcionFinalidad`, `regiones`,
     `urlBasesReguladoras`.
- ⚠️ La API **limita las peticiones concurrentes** (responde 429/5xx con muchos hilos). Por eso el
  detalle se descarga con `--workers 2` y reintentos con backoff. No subas la concurrencia.

> El script deja un volcado crudo del índice en `data/raw_sample.json`. La CCAA se deriva del campo
> `regiones[]` (códigos NUTS) con fallback al nivel del órgano; ver `deriva_region()` en `fetch_data.py`.

## Puesta en marcha

```bash
# 1. (opcional) entorno virtual
python3 -m venv .venv && source .venv/bin/activate

# 2. dependencias (solo requests)
pip install -r requirements.txt

# 3. traer datos reales de la BDNS (índice + detalle de las ~1600 más recientes, ~3 min)
python fetch_data.py --paginas 8 --page-size 200 --workers 2

# 4. abrir el directorio
python -m http.server 8000
# → http://localhost:8000
```

Si no ejecutas el paso 3, `index.html` carga `data/sample.json` automáticamente, así que la web
funciona desde el primer segundo.

## Despliegue

Cualquier hosting estático sirve. El JSON generado se versiona o se regenera en CI:

- **GitHub Pages**: push de `index.html` + `data/convocatorias.json`.
- **GitHub Actions (recomendado)**: workflow diario que ejecuta `fetch_data.py` y commitea el JSON.
  Así el directorio se mantiene fresco solo. (Plantilla en CLAUDE.md.)

## Licencia y aviso legal

Datos: reutilización de datos públicos (Ley 38/2003, RD 130/2019). La BDNS publica respetando el
honor y la intimidad de las personas físicas. Verifica cada convocatoria en la fuente oficial antes
de actuar; este directorio es una capa de descubrimiento, no asesoramiento.
