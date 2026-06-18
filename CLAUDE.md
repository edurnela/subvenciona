# CLAUDE.md — Subvenciona

Contexto para Claude Code al trabajar en este proyecto.

## Qué es
Directorio estático (HTML + un script Python) de convocatorias de subvenciones públicas en España.
Datos de la **API oficial BDNS**. Cero backend en producción: `fetch_data.py` genera un JSON y
`index.html` lo consume. Pensado para hostearse gratis en GitHub Pages / Netlify / Vercel.

## La API (verificada en real, junio 2026, sin auth)
- Base: `https://www.infosubvenciones.es/bdnstrans/api` (espejo: `https://www.pap.hacienda.gob.es/bdnstrans/api`)
- Param `vpd=GE` obligatorio. `fechaDesde` en formato **DD/MM/YYYY** (no ISO, devuelve 400).
- **Fetch en DOS fases** (clave): el endpoint de búsqueda es solo un índice ligero.
  1. `GET /convocatorias/busqueda?vpd=GE&page=0&pageSize=200` → ÍNDICE: `numeroConvocatoria`,
     `descripcion` (título), `nivel1/2/3` (organismo), `fechaRecepcion`. Ordenado reciente→antiguo.
     Respuesta tipo Spring Page: la lista va en `content`. `totalElements` ≈ 637.000.
  2. `GET /convocatorias?vpd=GE&numConv=<n>` → DETALLE con lo que importa: `presupuestoTotal`,
     `fechaInicioSolicitud`, `fechaFinSolicitud`, `abierto`, `tiposBeneficiarios[]`, `sectores[]`,
     `descripcionFinalidad`, `regiones[]` (códigos NUTS "ES12 - …"), `urlBasesReguladoras`.
- ⚠️ La API **limita la concurrencia**: con >2 hilos responde 429/5xx y se pierden registros.
  `fetch_data.py` usa `--workers 2` + reintentos con backoff. ~1600 detalles ≈ 3 min. No subir hilos.
- CCAA: se deriva en `deriva_region()` desde `regiones[]` (mapa NUTS→CCAA, y nombre tras el guion),
  con fallback a `organo.nivel2`. ESTATAL / "ES - ESPAÑA" → "Toda España".

## Filtrar a lo "solicitable" (clave para autónomos/pymes)
El feed de la BDNS está dominado por ruido para este público. Dos campos del DETALLE lo distinguen:
- `tipoConvocatoria`: `"Concurrencia competitiva - …"` (solicitable) vs `"Concesión directa - …"`
  (nominativas/instrumentales, ya adjudicadas → ruido). → `es_competitiva()`.
- `tiposBeneficiarios[].descripcion`: excluir las que solo van a `"… QUE NO DESARROLLAN ACTIVIDAD
  ECONÓMICA"` (asociaciones, fundaciones, particulares). Conservar PYME / autónomos / empresa.
  → `es_para_actividad_economica()`.
- Por defecto `fetch_data.py` se queda solo con `competitiva AND para_empresas` (~5% del feed).
  `--incluir-no-solicitables` desactiva el filtro. El **importe mínimo** NO se filtra aquí: es un
  control de UI en `index.html` (`#minImporte`, por defecto 3.000 €).
- Cada registro lleva `tipo_convocatoria`, `competitiva` y `para_empresas` por si hay que reauditar.

## Colapso de líneas repetidas
Una convocatoria suele venir partida en líneas/lotes ("Línea 4c)", "LÍNEA 6"…) que inundaban el
listado. `clave_grupo(titulo, organo, fecha_fin)` agrupa esas líneas (prefijo de título cortado en
el marcador de línea + organismo + fecha de cierre) y `colapsa_grupos()` deja una representante
(la de mayor importe) con `_extra` = nº de líneas ocultas. Activo por defecto en `fetch_data.py`
(`--sin-colapsar` lo desactiva); el JSON diario ya viene colapsado. El frontend vuelve a colapsar
por `grupo` (idempotente) y muestra "+N líneas más de esta convocatoria".

## Tareas habituales
- **Probar en local:** `pip install -r requirements.txt && python fetch_data.py --solo-abiertas --paginas 3 && python -m http.server 8000`
- **Añadir un filtro** (p.ej. importe mínimo): añadir control en `.filters` de `index.html`,
  campo en `state`, y rama en `apply()`.
- **Mejorar el mapeo de sector/CCAA:** la BDNS a veces no trae CCAA limpia; se puede derivar del
  campo de órgano o del ámbito geográfico. Ver `normaliza()`.

## Auto-actualización diaria (recomendado)
Crear `.github/workflows/update.yml` para refrescar los datos solos:

```yaml
name: Actualizar convocatorias
on:
  schedule: [{cron: '0 5 * * *'}]   # 05:00 UTC cada día
  workflow_dispatch:
permissions:
  contents: write
jobs:
  fetch:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: '3.11'}
      - run: pip install -r requirements.txt
      - run: python fetch_data.py --solo-abiertas --paginas 10 --page-size 1000
      - name: Commit data
        run: |
          git config user.name "subvenciona-bot"
          git config user.email "bot@users.noreply.github.com"
          git add -f data/convocatorias.json
          git commit -m "data: actualización diaria $(date +%F)" || echo "sin cambios"
          git push
```
(Para que GitHub Pages sirva el JSON, quita `data/convocatorias.json` del `.gitignore` o usa `git add -f` como arriba.)

## Estilo del frontend
Identidad "gaceta oficial": papel cálido, sello vermellón, verde institucional, tipografía serif
con utilitaria Helvetica para datos. No convertir en el típico dashboard oscuro SaaS — la estética
"documento oficial pero usable" es parte del gancho.

## Ideas de crecimiento (para que se vuelva viral)
- Permalinks por filtro (`?region=Madrid&sector=Digitalización`) para compartir búsquedas.
- Suscripción por email a nuevas convocatorias de un filtro (encaja con tu stack: GHL + n8n).
- Página por CCAA y por sector → SEO ("subvenciones autónomos Madrid 2026").
- Botón "compartir esta convocatoria" con tarjeta OpenGraph generada.
