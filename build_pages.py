#!/usr/bin/env python3
"""build_pages.py — Genera las páginas de categoría SEO de Ayudas Abiertas.

Se ejecuta DESPUÉS de fetch_data.py: lee data/convocatorias.json (no lo modifica)
y escribe páginas estáticas en subvenciones/, más sitemap.xml y robots.txt.

Páginas generadas (umbral: MIN_CONV convocatorias):
  /subvenciones/<comunidad>/<sector>/   comunidad × sector (excluye regiones no-CCAA)
  /subvenciones/<comunidad>/            página madre de comunidad (lista sus sectores)
  /subvenciones/sector/<sector>/        sector a nivel nacional (incluye Toda España, etc.)

Modelo visual y los 4 bloques de Schema JSON-LD replican categoria-plantilla.html.

Uso:  python build_pages.py
"""

import html
import json
import re
import shutil
import unicodedata
from collections import defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import quote

BASE = Path(__file__).parent
DATA_FILE = BASE / "data" / "convocatorias.json"
INDEX_FILE = BASE / "index.html"
SUBV_DIR = BASE / "subvenciones"
SITEMAP = BASE / "sitemap.xml"
ROBOTS = BASE / "robots.txt"

DOMAIN = "https://ayudasabiertas.com"
ANYO = date.today().year          # año mostrado en titles/H1 (se actualiza solo)
MIN_CONV = 3                      # mínimo de convocatorias para generar una página
# Valores de `region` que NO son una comunidad autónoma real (se excluyen de las
# páginas de comunidad; sí cuentan para las páginas de sector nacionales).
NO_CCAA = {"Toda España", "Varias comunidades", ""}

esc = html.escape

# --- CSS copiado VERBATIM de categoria-plantilla.html (bloque <style>) ----------
CSS = """  :root{
    --ink:#10221b; --paper:#f3efe4; --paper-2:#e9e3d2; --line:#cdc6b2;
    --sello:#b4351f; --sello-soft:#d6643f; --gold:#9a7b18; --ok:#2f6b4f;
    --muted:#5d6258; --card:#fbf9f2;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;background:var(--paper);color:var(--ink);
    font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
    -webkit-font-smoothing:antialiased;line-height:1.6}
  .wrap{max-width:860px;margin:0 auto;padding:0 22px}
  a{color:var(--sello)}

  /* Cabecera de marca */
  header.cat-head{border-bottom:2px solid var(--ink);background:var(--paper)}
  .cat-head-inner{padding:22px 0 18px;display:flex;align-items:baseline;
    justify-content:space-between;gap:16px;flex-wrap:wrap}
  .cat-brand{font-size:24px;font-weight:800;letter-spacing:-.01em;
    text-decoration:none;color:var(--ink)}
  .cat-brand .sello{color:var(--sello)}
  .cat-nav{font-family:"Helvetica Neue",Arial,sans-serif;font-size:13px}
  .cat-nav a{text-decoration:none;font-weight:600;margin-left:18px}

  /* Migas de pan */
  .breadcrumb{font-family:"Helvetica Neue",Arial,sans-serif;font-size:12.5px;
    color:var(--muted);padding:16px 0 0}
  .breadcrumb a{color:var(--muted);text-decoration:none}
  .breadcrumb a:hover{text-decoration:underline}
  .breadcrumb .sep{margin:0 7px;color:var(--line)}

  main{padding:0 0 64px}
  .doc-kicker{font-family:"Helvetica Neue",Arial,sans-serif;font-size:11.5px;
    letter-spacing:.14em;text-transform:uppercase;color:var(--sello);
    font-weight:700;margin:24px 0 8px}
  h1{font-size:clamp(28px,5vw,40px);line-height:1.1;margin:0 0 14px;font-weight:800}
  .intro{font-size:17px;color:var(--ink);max-width:62ch}
  .intro b{color:var(--ink)}

  /* Barra de stats */
  .stats{display:flex;gap:30px;flex-wrap:wrap;margin:26px 0 8px;
    padding:16px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
  .stat .n{font-size:26px;font-weight:800;color:var(--sello)}
  .stat .l{font-family:"Helvetica Neue",Arial,sans-serif;font-size:12px;
    text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}

  /* CTA de suscripción */
  .cta-box{background:var(--card);border:1px solid var(--line);
    border-left:3px solid var(--sello);border-radius:3px;padding:20px 22px;margin:28px 0}
  .cta-box h2{font-size:18px;margin:0 0 6px;font-weight:800}
  .cta-box p{font-size:14.5px;color:var(--muted);margin:0 0 14px}
  .cta-btn{display:inline-block;background:var(--sello);color:#fff;
    font-family:"Helvetica Neue",Arial,sans-serif;font-weight:700;font-size:14px;
    text-decoration:none;padding:11px 20px;border-radius:3px}
  .cta-btn:hover{background:#9a2c18}

  /* Secciones */
  h2.sec{font-size:21px;margin:38px 0 4px;font-weight:800;
    padding-top:20px;border-top:1px solid var(--line)}
  .sec-note{font-family:"Helvetica Neue",Arial,sans-serif;font-size:13px;
    color:var(--muted);margin:0 0 16px}

  /* Tarjeta de convocatoria */
  .conv{border:1px solid var(--line);border-radius:6px;padding:16px 18px;
    margin:0 0 14px;background:var(--card)}
  .conv.cerrada{opacity:.66;background:transparent}
  .conv-top{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}
  .conv h3{font-size:16.5px;line-height:1.3;margin:0;font-weight:700}
  .conv h3 a{color:var(--sello);text-decoration:none}
  .conv h3 a:hover{text-decoration:underline}
  .badge{flex-shrink:0;font-family:"Helvetica Neue",Arial,sans-serif;font-size:11px;
    font-weight:700;text-transform:uppercase;letter-spacing:.04em;
    padding:3px 9px;border-radius:20px;white-space:nowrap}
  .badge.abierta{background:#e3f0e8;color:var(--ok)}
  .badge.cerrada{background:#efe8e6;color:#8a5a4e}
  .conv-meta{font-family:"Helvetica Neue",Arial,sans-serif;font-size:13px;
    color:var(--muted);margin:8px 0 0;display:flex;flex-wrap:wrap;gap:6px 16px}
  .conv-meta b{color:var(--ink);font-weight:600}
  /* Destacado de "N abiertas" en los listados de sector (páginas madre) */
  .conv-meta .abierta-n{background:#e3f0e8;color:var(--ok);font-weight:700;
    padding:1px 9px;border-radius:20px}

  /* FAQ */
  details.faq{border-bottom:1px solid var(--line);padding:14px 0}
  details.faq summary{font-size:16px;font-weight:700;cursor:pointer;
    list-style:none;display:flex;justify-content:space-between;align-items:center}
  details.faq summary::-webkit-details-marker{display:none}
  details.faq summary::after{content:"+";color:var(--sello);font-size:22px;
    font-weight:400;margin-left:12px}
  details.faq[open] summary::after{content:"–"}
  details.faq p{font-size:15px;color:var(--muted);margin:12px 0 4px;max-width:64ch}

  /* Enlaces internos a categorías relacionadas */
  .related{margin:14px 0 0;display:flex;flex-wrap:wrap;gap:8px}
  .related a{font-family:"Helvetica Neue",Arial,sans-serif;font-size:13px;
    text-decoration:none;background:var(--paper-2);color:var(--ink);
    padding:7px 13px;border-radius:20px;border:1px solid var(--line)}
  .related a:hover{border-color:var(--sello);color:var(--sello)}

  footer{border-top:2px solid var(--ink);background:var(--paper);
    font-family:"Helvetica Neue",Arial,sans-serif;font-size:13px;color:var(--muted);margin-top:40px}
  .footer-inner{padding:22px 0 30px}
  .footer-inner a{color:var(--sello);text-decoration:none}"""

HEADER = """<header class="cat-head">
  <div class="wrap cat-head-inner">
    <a href="/" class="cat-brand">Ayudas <span class="sello">Abiertas</span></a>
    <nav class="cat-nav">
      <a href="/">Directorio</a>
      <a href="/#suscribirse">Recibir avisos</a>
    </nav>
  </div>
</header>"""

FOOTER = """<footer>
  <div class="wrap footer-inner">
    <p>Ayudas Abiertas · Datos abiertos reutilizados de la BDNS (IGAE, Ministerio de Hacienda) ·
      sitio independiente, España. <a href="/">Volver al directorio</a> ·
      <a href="/privacidad.html">Privacidad</a></p>
  </div>
</footer>"""


# ------------------------------------------------------------------ helpers ----
def slugify(s):
    """'País Vasco' → 'pais-vasco'; 'Investigación, desarrollo e innovación' →
    'investigacion-desarrollo-e-innovacion'. Quita acentos/eñes, comas y espacios → '-'."""
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")  # quita acentos
    s = re.sub(r"[^a-z0-9 ]", " ", s)        # comas, guiones, etc. → espacio
    return re.sub(r"\s+", "-", s.strip())


def euros(n):
    """185642.82 → '185.643 €' (formato español, sin decimales)."""
    try:
        return f"{round(float(n)):,}".replace(",", ".") + " €"
    except (TypeError, ValueError):
        return ""


def fmt_fecha(f):
    """'2026-07-31' → '31/07/2026'."""
    if not f:
        return ""
    p = str(f)[:10].split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 else str(f)


def es_abierta(c):
    hoy = date.today().isoformat()
    fin = (c.get("fecha_fin") or "")[:10] or None
    ini = (c.get("fecha_inicio") or "")[:10] or None
    if ini and ini > hoy:
        return False          # el plazo aún no ha empezado
    if fin:
        return fin >= hoy     # si hay fecha de cierre, manda ella
    return bool(c.get("abierta"))  # sin fecha_fin, nos fiamos del flag


def ld(obj):
    """Bloque <script> con JSON-LD a partir de un dict."""
    return ('<script type="application/ld+json">\n'
            + json.dumps(obj, ensure_ascii=False, indent=2)
            + "\n</script>")


ORGANIZATION_LD = ld({
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Ayudas Abiertas",
    "url": DOMAIN + "/",
    "description": "Subvenciones para autónomos y pymes en España",
    # "logo": DOMAIN + "/logo.png",   # descomentar SOLO cuando exista el archivo en el repo
})


def breadcrumb_ld(items):
    """items = [(nombre, url), ...] en orden."""
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": u}
            for i, (n, u) in enumerate(items)
        ],
    }


def collection_ld(name, description, url, convs):
    """CollectionPage con ItemList anidado de convocatorias."""
    return {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": name,
        "description": description,
        "url": url,
        "isPartOf": {"@type": "WebSite", "name": "Ayudas Abiertas", "url": DOMAIN + "/"},
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": i + 1, "name": c["titulo"],
                 "url": c.get("url_oficial") or DOMAIN + "/"}
                for i, c in enumerate(convs)
            ],
        },
    }


def faq_ld(qas):
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qas
        ],
    }


def card(c):
    """Tarjeta de convocatoria (abierta o cerrada según c['abierta'])."""
    abierta = es_abierta(c)
    cls = "conv" if abierta else "conv cerrada"
    badge = ('<span class="badge abierta">Abierta</span>' if abierta
             else '<span class="badge cerrada">Cerrada</span>')
    url = esc(c.get("url_oficial") or "#")
    meta = [f'<span><b>Órgano:</b> {esc(c.get("organo") or "—")}</span>']
    if c.get("importe"):
        meta.append(f'<span><b>Importe:</b> {euros(c["importe"])}</span>')
    if abierta and c.get("fecha_fin"):
        meta.append(f'<span><b>Plazo:</b> hasta {fmt_fecha(c["fecha_fin"])}</span>')
    if c.get("nivel_admin"):
        meta.append(f'<span><b>Ámbito:</b> {esc(c["nivel_admin"])}</span>')
    extra = ""
    if c.get("_extra"):
        extra = (f'<span style="color:var(--gold)">+{c["_extra"]} '
                 f'línea{"s" if c["_extra"] != 1 else ""} más de esta convocatoria</span>')
        meta.append(extra)
    return f"""    <article class="{cls}">
      <div class="conv-top">
        <h3><a href="{url}" rel="nofollow noopener" target="_blank">{esc(c.get("titulo") or "")}</a></h3>
        {badge}
      </div>
      <div class="conv-meta">
        {"".join(meta)}
      </div>
    </article>"""


def faq_html(qas):
    bloques = []
    for q, a in qas:
        bloques.append(f"""    <details class="faq">
      <summary>{esc(q)}</summary>
      <p>{esc(a)}</p>
    </details>""")
    return "\n".join(bloques)


def related_html(links):
    """links = [(label, href), ...] — solo URLs que realmente se generan."""
    if not links:
        return ""
    chips = "\n".join(f'      <a href="{esc(h)}">{esc(l)}</a>' for l, h in links)
    return f"""    <h2 class="sec">Otras categorías</h2>
    <p class="sec-note">Explora subvenciones relacionadas.</p>
    <div class="related">
{chips}
    </div>"""


def stats_html(stats):
    cels = "".join(
        f'<div class="stat"><div class="n">{n}</div><div class="l">{l}</div></div>'
        for n, l in stats
    )
    return f'    <div class="stats">{cels}</div>'


def page(*, title, description, canonical, og_title, og_desc,
         ld_blocks, breadcrumb_visible, kicker, h1, intro, stats,
         cta_h2, cta_p, cta_href, body_sections):
    """Ensambla un documento HTML completo con el estilo de la plantilla."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">

<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{esc(canonical)}">

<meta property="og:type" content="website">
<meta property="og:site_name" content="Ayudas Abiertas">
<meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(og_desc)}">
<meta property="og:url" content="{esc(canonical)}">

<style>
{CSS}
</style>

{ORGANIZATION_LD}
{chr(10).join(ld_blocks)}
</head>
<body>

{HEADER}

<main>
  <div class="wrap">

    <nav class="breadcrumb" aria-label="Migas de pan">
      {breadcrumb_visible}
    </nav>

    <p class="doc-kicker">{esc(kicker)}</p>
    <h1>{esc(h1)}</h1>

    <p class="intro">{intro}</p>

{stats_html(stats)}

    <div class="cta-box">
      <h2>{esc(cta_h2)}</h2>
      <p>{esc(cta_p)}</p>
      <a class="cta-btn" href="{esc(cta_href)}">Avísame de nuevas ayudas →</a>
    </div>

{body_sections}

  </div>
</main>

{FOOTER}

</body>
</html>
"""


def write(path: Path, contenido: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contenido, encoding="utf-8")


# --------------------------------------------------------------- generadores ----
def faqs_categoria(sector, ambito):
    """ambito = 'el País Vasco' / 'España'. FAQ genérica parametrizada."""
    return [
        (f"¿Quién puede solicitar subvenciones de {sector} en {ambito}?",
         "Depende de cada convocatoria. Suelen poder solicitarlas pymes, autónomos y "
         "empresas, además de otras entidades, según las bases de cada ayuda. Este "
         "directorio prioriza convocatorias en concurrencia competitiva dirigidas a "
         "quienes desarrollan actividad económica. Cada convocatoria detalla sus "
         "beneficiarios concretos en las bases reguladoras, enlazadas en cada ficha."),
        (f"¿Cada cuánto se publican nuevas ayudas de {sector} en {ambito}?",
         "Se publican a lo largo de todo el año, sin un calendario fijo. Ayudas Abiertas "
         "revisa la Base de Datos Nacional de Subvenciones (BDNS) a diario, por lo que "
         "esta página se actualiza automáticamente cada día con las convocatorias nuevas."),
        ("¿Dónde se presenta la solicitud?",
         "Cada convocatoria se tramita ante el organismo que la convoca, normalmente a "
         "través de su sede electrónica. En cada ficha enlazamos a la convocatoria oficial "
         "en la BDNS y a sus bases reguladoras, donde se indica el procedimiento exacto."),
        ("¿Es gratis recibir avisos de nuevas convocatorias?",
         "Sí. Ayudas Abiertas es un servicio gratuito. Puedes suscribirte con tu email "
         f"para recibir un aviso cuando se publique una nueva subvención de {sector} en "
         f"{ambito}, y darte de baja cuando quieras."),
    ]


def secciones_convocatorias(convs, sector, ambito, empty_text):
    """Bloque abiertas (protagonismo) + cerradas (relegadas)."""
    abiertas = sorted([c for c in convs if es_abierta(c)],
                      key=lambda c: c.get("importe") or 0, reverse=True)
    cerradas = sorted([c for c in convs if not es_abierta(c)],
                      key=lambda c: c.get("importe") or 0, reverse=True)
    out = ['    <h2 class="sec">Convocatorias abiertas</h2>']
    if abiertas:
        out.append('    <p class="sec-note">Puedes presentar tu solicitud ahora mismo.</p>')
        out += [card(c) for c in abiertas]
    else:
        out.append('    <p class="sec-note">Puedes presentar tu solicitud ahora mismo.</p>')
        out.append('    <p class="sec-note" style="background:var(--card);border:1px dashed var(--line);'
                   'border-radius:6px;padding:16px 18px">' + esc(empty_text) + '</p>')
    if cerradas:
        out.append('    <h2 class="sec">Convocatorias cerradas</h2>')
        out.append('    <p class="sec-note">Plazo finalizado. Se mantienen como referencia y '
                   'para consultar las bases de cara a próximas ediciones.</p>')
        out += [card(c) for c in cerradas]
    return "\n".join(out)


def render_comunidad_sector(comunidad, sector, convs, generados):
    com_slug, sec_slug = slugify(comunidad), slugify(sector)
    url = f"{DOMAIN}/subvenciones/{com_slug}/{sec_slug}/"
    n = len(convs)
    n_ab = sum(1 for c in convs if es_abierta(c))
    total = sum(c.get("importe") or 0 for c in convs)
    title = f"Subvenciones de {sector} en {comunidad} {ANYO} · Ayudas Abiertas"
    desc = (f"Todas las subvenciones y ayudas de {sector} en {comunidad} en {ANYO}. "
            "Convocatorias actualizadas a diario desde la BDNS. Recibe avisos por email "
            "cuando se publiquen nuevas.")
    h1 = f"Subvenciones de {sector} en {comunidad}"
    intro = (f"Esta página reúne todas las <b>subvenciones y ayudas de {esc(sector)} en "
             f"{esc(comunidad)}</b> recogidas en la Base de Datos Nacional de Subvenciones "
             "(BDNS). <b>Se actualiza a diario</b>: primero verás las convocatorias abiertas "
             "y, más abajo, las ya cerradas como referencia.")
    qas = faqs_categoria(sector, f"{comunidad}")
    empty = (f"Ahora mismo no hay convocatorias de {sector} abiertas en {comunidad}. "
             "Suscríbete arriba y te avisamos en cuanto se publique una nueva.")

    # Enlaces internos: solo URLs que realmente se generan.
    rel = []
    for c2 in sorted(generados["por_sector"].get(sector, [])):
        if c2 != comunidad:
            rel.append((f"{sector} en {c2}",
                        f"/subvenciones/{slugify(c2)}/{sec_slug}/"))
    rel = rel[:5]
    otros = []
    for s2 in sorted(generados["por_comunidad"].get(comunidad, [])):
        if s2 != sector:
            otros.append((f"{s2} en {comunidad}",
                          f"/subvenciones/{com_slug}/{slugify(s2)}/"))
    rel += otros[:5]
    rel.append((f"Todas las de {comunidad}", f"/subvenciones/{com_slug}/"))
    if sector in generados["sectores_nacionales"]:
        rel.append((f"{sector} en toda España", f"/subvenciones/sector/{sec_slug}/"))

    body = "\n\n".join([
        secciones_convocatorias(convs, sector, comunidad, empty),
        '    <h2 class="sec">Preguntas frecuentes</h2>\n' + faq_html(qas),
        related_html(rel),
    ])
    ld_blocks = [
        ld(breadcrumb_ld([
            ("Inicio", DOMAIN + "/"),
            (comunidad, f"{DOMAIN}/subvenciones/{com_slug}/"),
            (sector, url),
        ])),
        ld(collection_ld(f"Subvenciones de {sector} en {comunidad} {ANYO}",
                         f"Convocatorias de subvenciones de {sector} abiertas en "
                         f"{comunidad}, actualizadas a diario desde la BDNS.", url, convs)),
        ld(faq_ld(qas)),
    ]
    bc = (f'<a href="/">Inicio</a><span class="sep">›</span>\n'
          f'      <a href="/subvenciones/{com_slug}/">{esc(comunidad)}</a>'
          f'<span class="sep">›</span>\n      <span>{esc(sector)}</span>')
    doc = page(
        title=title, description=desc, canonical=url,
        og_title=f"Subvenciones de {sector} en {comunidad} {ANYO}",
        og_desc=f"Convocatorias de {sector} en {comunidad}, actualizadas a diario desde la BDNS.",
        ld_blocks=ld_blocks, breadcrumb_visible=bc,
        kicker=f"{sector} · {comunidad}", h1=h1, intro=intro,
        stats=[(n, "Convocatorias"), (n_ab, "Abiertas ahora"), (euros(total) or "—", "Importe acumulado")],
        cta_h2=f"Recibe nuevas ayudas de {sector} de {comunidad}",
        cta_p="Te avisamos por email en cuanto se publique una convocatoria nueva de esta categoría. Gratis y sin spam.",
        cta_href=f"/?ccaa={quote(comunidad)}&sector={quote(sector)}#suscribirse",
        body_sections=body,
    )
    write(SUBV_DIR / com_slug / sec_slug / "index.html", doc)
    return url


def render_sector_nacional(sector, convs, generados):
    sec_slug = slugify(sector)
    url = f"{DOMAIN}/subvenciones/sector/{sec_slug}/"
    n = len(convs)
    n_ab = sum(1 for c in convs if es_abierta(c))
    total = sum(c.get("importe") or 0 for c in convs)
    title = f"Subvenciones de {sector} en España {ANYO} · Ayudas Abiertas"
    desc = (f"Todas las subvenciones y ayudas de {sector} en España en {ANYO}. "
            "Convocatorias estatales y autonómicas actualizadas a diario desde la BDNS. "
            "Recibe avisos por email cuando se publiquen nuevas.")
    h1 = f"Subvenciones de {sector} en España"
    intro = (f"Esta página reúne todas las <b>subvenciones y ayudas de {esc(sector)} en "
             "España</b> recogidas en la Base de Datos Nacional de Subvenciones (BDNS): "
             "estatales, autonómicas y locales. <b>Se actualiza a diario</b>: primero verás "
             "las convocatorias abiertas y, más abajo, las ya cerradas como referencia.")
    qas = faqs_categoria(sector, "España")
    empty = (f"Ahora mismo no hay convocatorias de {sector} abiertas en España. "
             "Suscríbete arriba y te avisamos en cuanto se publique una nueva.")

    rel = []
    for c2 in sorted(generados["por_sector"].get(sector, [])):
        rel.append((f"{sector} en {c2}", f"/subvenciones/{slugify(c2)}/{sec_slug}/"))
    rel = rel[:6]
    for s2 in sorted(generados["sectores_nacionales"]):
        if s2 != sector:
            rel.append((f"{s2} en España", f"/subvenciones/sector/{slugify(s2)}/"))
    rel = rel[:11]

    body = "\n\n".join([
        secciones_convocatorias(convs, sector, "España", empty),
        '    <h2 class="sec">Preguntas frecuentes</h2>\n' + faq_html(qas),
        related_html(rel),
    ])
    ld_blocks = [
        ld(breadcrumb_ld([("Inicio", DOMAIN + "/"), (sector, url)])),
        ld(collection_ld(f"Subvenciones de {sector} en España {ANYO}",
                         f"Convocatorias de subvenciones de {sector} en España, "
                         "actualizadas a diario desde la BDNS.", url, convs)),
        ld(faq_ld(qas)),
    ]
    bc = (f'<a href="/">Inicio</a><span class="sep">›</span>\n'
          f'      <span>{esc(sector)}</span>')
    doc = page(
        title=title, description=desc, canonical=url,
        og_title=f"Subvenciones de {sector} en España {ANYO}",
        og_desc=f"Convocatorias de {sector} en España, actualizadas a diario desde la BDNS.",
        ld_blocks=ld_blocks, breadcrumb_visible=bc,
        kicker=f"{sector} · España", h1=h1, intro=intro,
        stats=[(n, "Convocatorias"), (n_ab, "Abiertas ahora"), (euros(total) or "—", "Importe acumulado")],
        cta_h2=f"Recibe nuevas ayudas de {sector}",
        cta_p="Te avisamos por email en cuanto se publique una convocatoria nueva de este sector. Gratis y sin spam.",
        cta_href=f"/?sector={quote(sector)}#suscribirse",
        body_sections=body,
    )
    write(SUBV_DIR / "sector" / sec_slug / "index.html", doc)
    return url


def render_comunidad(comunidad, sectores, convs_por_sector, generados):
    """Página madre: lista y enlaza los sectores de la comunidad."""
    com_slug = slugify(comunidad)
    url = f"{DOMAIN}/subvenciones/{com_slug}/"
    todas = [c for s in sectores for c in convs_por_sector[(comunidad, s)]]
    n = len(todas)
    n_ab = sum(1 for c in todas if es_abierta(c))
    total = sum(c.get("importe") or 0 for c in todas)
    title = f"Subvenciones y ayudas en {comunidad} {ANYO} · Ayudas Abiertas"
    desc = (f"Todas las subvenciones y ayudas abiertas en {comunidad} en {ANYO}, por sector. "
            "Convocatorias actualizadas a diario desde la BDNS.")
    h1 = f"Subvenciones y ayudas en {comunidad}"
    intro = (f"Explora las <b>subvenciones y ayudas en {esc(comunidad)}</b> recogidas en la "
             "Base de Datos Nacional de Subvenciones (BDNS), organizadas por sector. "
             "<b>Se actualiza a diario.</b> Elige un sector para ver sus convocatorias "
             "abiertas y cerradas.")

    # Tarjetas-sector: primero los sectores con alguna convocatoria abierta y,
    # debajo, los que solo tienen cerradas. Dentro de cada grupo, orden alfabético.
    tarjetas = ['    <h2 class="sec">Sectores con convocatorias</h2>',
                '    <p class="sec-note">Primero los sectores con convocatorias abiertas. '
                'Elige uno para ver el detalle.</p>']
    items_ld = []
    abiertas_de = lambda s: sum(1 for c in convs_por_sector[(comunidad, s)] if es_abierta(c))
    orden = sorted(sectores, key=lambda s: (abiertas_de(s) == 0, s))
    for s in orden:
        cs = convs_por_sector[(comunidad, s)]
        ab = abiertas_de(s)
        tot = sum(c.get("importe") or 0 for c in cs)
        href = f"/subvenciones/{com_slug}/{slugify(s)}/"
        items_ld.append({"@type": "ListItem", "position": len(items_ld) + 1,
                         "name": f"{s} en {comunidad}", "url": DOMAIN + href})
        meta = [f'<span>{len(cs)} convocatoria{"s" if len(cs) != 1 else ""}</span>']
        if ab:
            meta.append(f'<span class="abierta-n">{ab} abierta{"s" if ab != 1 else ""}</span>')
        if tot:
            meta.append(f'<span>{euros(tot)}</span>')
        tarjetas.append(f"""    <article class="conv">
      <div class="conv-top">
        <h3><a href="{esc(href)}">{esc(s)} en {esc(comunidad)}</a></h3>
      </div>
      <div class="conv-meta">{"".join(meta)}</div>
    </article>""")

    # Relacionadas: otras comunidades (madre) que existen
    rel = []
    for c2 in sorted(generados["comunidades"]):
        if c2 != comunidad:
            rel.append((f"Ayudas en {c2}", f"/subvenciones/{slugify(c2)}/"))
    rel = rel[:8]

    body = "\n".join(tarjetas) + "\n\n" + related_html(rel)
    collection = {
        "@context": "https://schema.org", "@type": "CollectionPage",
        "name": f"Subvenciones y ayudas en {comunidad} {ANYO}",
        "description": f"Sectores con subvenciones abiertas en {comunidad}, actualizado a diario desde la BDNS.",
        "url": url,
        "isPartOf": {"@type": "WebSite", "name": "Ayudas Abiertas", "url": DOMAIN + "/"},
        "mainEntity": {"@type": "ItemList", "itemListElement": items_ld},
    }
    ld_blocks = [
        ld(breadcrumb_ld([("Inicio", DOMAIN + "/"), (comunidad, url)])),
        ld(collection),
    ]
    bc = (f'<a href="/">Inicio</a><span class="sep">›</span>\n'
          f'      <span>{esc(comunidad)}</span>')
    doc = page(
        title=title, description=desc, canonical=url,
        og_title=f"Subvenciones y ayudas en {comunidad} {ANYO}",
        og_desc=f"Convocatorias en {comunidad} por sector, actualizadas a diario desde la BDNS.",
        ld_blocks=ld_blocks, breadcrumb_visible=bc,
        kicker=f"Comunidad · {comunidad}", h1=h1, intro=intro,
        stats=[(n, "Convocatorias"), (n_ab, "Abiertas ahora"), (euros(total) or "—", "Importe acumulado")],
        cta_h2=f"Recibe nuevas ayudas de {comunidad}",
        cta_p="Te avisamos por email en cuanto se publique una convocatoria nueva en tu comunidad. Gratis y sin spam.",
        cta_href=f"/?ccaa={quote(comunidad)}#suscribirse",
        body_sections=body,
    )
    write(SUBV_DIR / com_slug / "index.html", doc)
    return url


def escribe_sitemap(urls):
    hoy = __import__("datetime").date.today().isoformat()
    cuerpo = "\n".join(
        f"  <url><loc>{esc(u)}</loc><lastmod>{hoy}</lastmod></url>" for u in urls
    )
    SITEMAP.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{cuerpo}\n</urlset>\n", encoding="utf-8")


def actualiza_footer_index(sectores_nac, combos, comunidades):
    """Rescribe en index.html (entre marcadores) los enlaces a las páginas de
    categoría que SÍ se generan: sectores nacionales + comunidades, ambos por
    volumen de convocatorias (las más importantes primero). Idempotente."""
    if not INDEX_FILE.exists():
        return
    src = INDEX_FILE.read_text(encoding="utf-8")

    sec_items = sorted(sectores_nac.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    sec_li = "\n".join(
        f'        <li><a href="/subvenciones/sector/{slugify(s)}/">{esc(s)}</a></li>'
        for s, _ in sec_items)

    com_total = defaultdict(int)
    for (com, _sec), cs in combos.items():
        com_total[com] += len(cs)
    com_items = sorted(comunidades, key=lambda c: (-com_total[c], c))
    com_li = "\n".join(
        f'        <li><a href="/subvenciones/{slugify(c)}/">{esc(c)}</a></li>'
        for c in com_items)

    bloque = (
        "<!-- CATEGORIAS:INICIO — bloque generado por build_pages.py; no editar a mano -->\n"
        '    <nav class="foot-cats" aria-label="Categorías de subvenciones">\n'
        "      <div>\n        <h3>Subvenciones por sector</h3>\n        <ul>\n"
        f"{sec_li}\n        </ul>\n      </div>\n"
        "      <div>\n        <h3>Subvenciones por comunidad</h3>\n        <ul>\n"
        f"{com_li}\n        </ul>\n      </div>\n"
        "    </nav>\n    <!-- CATEGORIAS:FIN -->")

    nuevo, n = re.subn(
        r"<!-- CATEGORIAS:INICIO.*?CATEGORIAS:FIN -->",
        lambda _m: bloque, src, flags=re.S)
    if not n:
        print("[!] index.html: no encuentro los marcadores CATEGORIAS; footer sin tocar")
        return
    if nuevo != src:
        INDEX_FILE.write_text(nuevo, encoding="utf-8")
    print(f"[ok] Footer de index.html: {len(sec_items)} sectores + {len(com_items)} comunidades")


def escribe_robots():
    if ROBOTS.exists():
        return
    ROBOTS.write_text(
        "User-agent: *\nAllow: /\n\n"
        f"Sitemap: {DOMAIN}/sitemap.xml\n", encoding="utf-8")


def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    convs = data["convocatorias"]

    # Agrupaciones
    por_combo = defaultdict(list)      # (comunidad, sector) -> [conv]
    por_sector_nac = defaultdict(list)  # sector -> [conv]  (todas, incl. Toda España)
    for c in convs:
        region, sector = c.get("region") or "", c.get("sector") or ""
        if not sector:
            continue
        por_sector_nac[sector].append(c)
        if region not in NO_CCAA:
            por_combo[(region, sector)].append(c)

    combos = {k: v for k, v in por_combo.items() if len(v) >= MIN_CONV}
    sectores_nac = {s: v for s, v in por_sector_nac.items() if len(v) >= MIN_CONV}

    # Índices de lo que SÍ se va a generar (para enlaces internos válidos)
    comunidades = sorted({com for (com, _s) in combos})
    por_comunidad = defaultdict(set)   # comunidad -> {sectores con página}
    por_sector = defaultdict(set)      # sector -> {comunidades con página}
    for (com, sec) in combos:
        por_comunidad[com].add(sec)
        por_sector[sec].add(com)
    generados = {
        "por_comunidad": por_comunidad,
        "por_sector": por_sector,
        "comunidades": set(comunidades),
        "sectores_nacionales": set(sectores_nac),
    }

    # Regenerar desde cero (elimina páginas de combos que ya no llegan al umbral)
    if SUBV_DIR.exists():
        shutil.rmtree(SUBV_DIR)

    urls = [DOMAIN + "/", DOMAIN + "/privacidad.html"]

    for (com, sec), cs in sorted(combos.items()):
        urls.append(render_comunidad_sector(com, sec, cs, generados))
    for com in comunidades:
        urls.append(render_comunidad(com, sorted(por_comunidad[com]), por_combo, generados))
    for sec, cs in sorted(sectores_nac.items()):
        urls.append(render_sector_nacional(sec, cs, generados))

    robots_existia = ROBOTS.exists()
    escribe_sitemap(urls)
    escribe_robots()
    actualiza_footer_index(sectores_nac, combos, set(comunidades))

    print(f"[ok] {len(combos)} páginas comunidad×sector")
    print(f"[ok] {len(comunidades)} páginas madre de comunidad")
    print(f"[ok] {len(sectores_nac)} páginas de sector nacional")
    print(f"[ok] sitemap.xml con {len(urls)} URLs")
    print(f"[ok] robots.txt {'ya existía' if robots_existia else 'creado'}")


if __name__ == "__main__":
    main()
