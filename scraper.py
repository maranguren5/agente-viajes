import os
import re
import json
import time
import smtplib
import requests
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

# ======================== CONFIGURACIÓN Y CREDENCIALES ======================== #
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", SENDER_EMAIL)

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
if os.environ.get("PAGES_URL"):
    PAGES_URL = os.environ.get("PAGES_URL")
elif GITHUB_REPOSITORY and "/" in GITHUB_REPOSITORY:
    owner, repo = GITHUB_REPOSITORY.split("/", 1)
    PAGES_URL = f"https://{owner}.github.io/{repo}"
else:
    PAGES_URL = ""

DIR_DATA = "data"
ARCHIVO_HISTORIAL = os.path.join(DIR_DATA, "historial_vuelos.json")
ARCHIVO_HTML_SALIDA = "index.html"

ORDEN_AEROPUERTOS = ["BSL", "GVA", "ZRH"]
NOMBRES_AEROPUERTOS = {
    "BSL": "Basilea (BSL)",
    "GVA": "Ginebra (GVA)",
    "ZRH": "Zúrich (ZRH)"
}

PRESUPUESTO_ESCALONADO_CHF = {
    1: 47.5,
    2: 45.0,
    3: 55.0,
    4: 70.0
}

DESTINOS_DIRECTOS = {
    "BSL": [
        "LON", "PMI", "OPO", "LIS", "FAO", "BUD", "KRK", "WAW", "WRO", 
        "BER", "HAM", "VIE", "AMS", "CDG", "ROM", "PRN", "SKP", "TIA", 
        "BCN", "MAD", "VLC", "AGP", "NAP", "CTA", "MLA", "DUB", "EDI"
    ],
    "GVA": [
        "LON", "MAN", "LIS", "OPO", "PMI", "CDG", "AMS", "BRU", "VIE", 
        "ROM", "BCN", "MAD", "ATH", "PRG", "CPH", "OSL", "ARN", "DUB"
    ],
    "ZRH": [
        "LON", "BER", "HAM", "VIE", "AMS", "CDG", "LIS", "PMI", "ROM", 
        "PRG", "BCN", "MAD", "VCE", "MIL", "OPO", "DUB", "BUD", "WAW"
    ]
}

NOMBRES_CIUDADES = {
    "LON": "Londres", "PMI": "Palma de Mallorca", "OPO": "Oporto", "LIS": "Lisboa",
    "FAO": "Faro", "BUD": "Budapest", "KRK": "Cracovia", "WAW": "Varsovia",
    "WRO": "Breslavia", "BER": "Berlín", "HAM": "Hamburgo", "VIE": "Viena",
    "AMS": "Ámsterdam", "CDG": "París", "ROM": "Roma", "PRN": "Pristina",
    "SKP": "Skopie", "TIA": "Tirana", "BCN": "Barcelona", "MAD": "Madrid",
    "VLC": "Valencia", "AGP": "Málaga", "NAP": "Nápoles", "CTA": "Catania",
    "MLA": "Malta", "DUB": "Dublín", "EDI": "Edimburgo", "MAN": "Mánchester",
    "BRU": "Bruselas", "ATH": "Atenas", "PRG": "Praga", "CPH": "Copenhague",
    "OSL": "Oslo", "ARN": "Estocolmo", "VCE": "Venecia", "MIL": "Milán"
}

# ======================== PERSISTENCIA LOCAL (COSTE 0) ======================== #
def cargar_historial():
    if os.path.exists(ARCHIVO_HISTORIAL):
        try:
            with open(ARCHIVO_HISTORIAL, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Error] Fallo cargando historial: {e}")
    return []

def guardar_historial(datos):
    os.makedirs(DIR_DATA, exist_ok=True)
    with open(ARCHIVO_HISTORIAL, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

# ======================== MOTOR 1: RYANAIR REST API ======================== #
def rastrear_ryanair(origen="BSL", dias_horizonte=30):
    vuelos = []
    hoy = datetime.now()
    fecha_limite = hoy + timedelta(days=dias_horizonte)
    url = "https://www.ryanair.com/api/farfnd/v4/roundTripFares"
    
    params = {
        "departureAirportIataCode": origen,
        "outboundDepartureDateFrom": hoy.strftime("%Y-%m-%d"),
        "outboundDepartureDateTo": fecha_limite.strftime("%Y-%m-%d"),
        "inboundDepartureDateFrom": hoy.strftime("%Y-%m-%d"),
        "inboundDepartureDateTo": (fecha_limite + timedelta(days=5)).strftime("%Y-%m-%d"),
        "currency": "CHF",
        "priceValueTo": 70.0
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            fares = r.json().get("fares", [])
            for f in fares:
                outbound = f.get("outbound", {})
                inbound = f.get("inbound", {})
                f_ida_str = outbound.get("departureDate", "")[:10]
                f_vta_str = inbound.get("departureDate", "")[:10]
                if not (f_ida_str and f_vta_str):
                    continue
                
                d_ida = datetime.strptime(f_ida_str, "%Y-%m-%d")
                d_vta = datetime.strptime(f_vta_str, "%Y-%m-%d")
                duracion = (d_vta - d_ida).days + 1
                if duracion not in [1, 2, 3, 4]:
                    continue
                
                precio_total = f.get("summary", {}).get("price", {}).get("value")
                if precio_total is None:
                    continue
                
                tope_chf = PRESUPUESTO_ESCALONADO_CHF.get(duracion, 70.0)
                if precio_total <= tope_chf:
                    dest_cod = outbound.get("arrivalAirport", {}).get("iataCode", "")
                    dest_nom = NOMBRES_CIUDADES.get(dest_cod, outbound.get("arrivalAirport", {}).get("name", dest_cod))
                    v_id = f"{origen}-{dest_cod}-{f_ida_str}-{f_vta_str}-{int(precio_total)}"
                    url_vuelo = f"https://www.google.com/travel/flights?q=Flights%20from%20{origen}%20to%20{dest_cod}%20on%20{f_ida_str}%20through%20{f_vta_str}&curr=CHF"

                    vuelos.append({
                        "id": v_id,
                        "origen_iata": origen,
                        "origen_nombre": NOMBRES_AEROPUERTOS.get(origen, origen),
                        "destino_codigo": dest_cod,
                        "destino_nombre": dest_nom,
                        "precio_chf": float(precio_total),
                        "presupuesto_max_chf": tope_chf,
                        "duracion_dias": duracion,
                        "fechas": f"{f_ida_str} al {f_vta_str}" if duracion > 1 else f"{f_ida_str} (mismo día)",
                        "fecha_ida": f_ida_str,
                        "fecha_vuelta": f_vta_str,
                        "aerolinea": "Ryanair",
                        "url": url_vuelo,
                        "fecha_deteccion": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                    })
    except Exception as e:
        print(f"[Ryanair Error {origen}] {e}")
    return vuelos

# ======================== MOTOR 2: EASYJET, SWISS Y MULTIAEROLÍNEA ======================== #
def rastrear_todas_aerolineas_http(origen="BSL"):
    vuelos = []
    hoy = datetime.now()
    destinos = DESTINOS_DIRECTOS.get(origen, [])[:8]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "es-CH,es;q=0.9,de-CH;q=0.8,en;q=0.7"
    }

    fechas_a_testear = []
    for d in range(1, 22):
        f_ida = hoy + timedelta(days=d)
        if f_ida.weekday() in [3, 4, 5]:
            for dur in [2, 3, 4]:
                f_vuelta = f_ida + timedelta(days=dur - 1)
                fechas_a_testear.append((f_ida.strftime("%Y-%m-%d"), f_vuelta.strftime("%Y-%m-%d"), dur))

    for dest_cod in destinos:
        dest_nom = NOMBRES_CIUDADES.get(dest_cod, dest_cod)
        for ida_str, vta_str, dur in fechas_a_testear[:4]:
            tope_chf = PRESUPUESTO_ESCALONADO_CHF.get(dur, 70.0)
            url_consulta = f"https://www.google.com/travel/flights?q=Round-trip%20flights%20from%20{origen}%20to%20{dest_cod}%20on%20{ida_str}%20through%20{vta_str}&hl=es-CH&gl=ch&curr=CHF"

            try:
                r = requests.get(url_consulta, headers=headers, timeout=6)
                if r.status_code == 200:
                    precios = re.findall(r"(?:CHF|Fr\.)\s*(\d+)", r.text)
                    if not precios:
                        precios = re.findall(r"(\d+)\s*(?:CHF|Fr\.)", r.text)

                    precios_validos = [float(p) for p in precios if 20.0 <= float(p) <= tope_chf]
                    if precios_validos:
                        precio_min = min(precios_validos)
                        aerolinea = "Directo (EasyJet/SWISS)"
                        if "easyjet" in r.text.lower():
                            aerolinea = "EasyJet"
                        elif "swiss" in r.text.lower():
                            aerolinea = "SWISS"

                        v_id = f"{origen}-{dest_cod}-{ida_str}-{vta_str}-{int(precio_min)}"
                        vuelos.append({
                            "id": v_id,
                            "origen_iata": origen,
                            "origen_nombre": NOMBRES_AEROPUERTOS.get(origen, origen),
                            "destino_codigo": dest_cod,
                            "destino_nombre": dest_nom,
                            "precio_chf": precio_min,
                            "presupuesto_max_chf": tope_chf,
                            "duracion_dias": dur,
                            "fechas": f"{ida_str} al {vta_str}",
                            "fecha_ida": ida_str,
                            "fecha_vuelta": vta_str,
                            "aerolinea": aerolinea,
                            "url": url_consulta,
                            "fecha_deteccion": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                        })
            except Exception:
                continue

    return vuelos

# ======================== COMPILADOR HTML (GITHUB PAGES) ======================== #
PLANTILLA_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Radar de Vuelos Directos Suiza</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f1f5f9; color: #0f172a; margin: 0; padding: 20px; }
    .container { max-width: 900px; margin: 0 auto; }
    .header { background: #0f172a; color: white; padding: 24px; border-radius: 12px; margin-bottom: 24px; text-align: center; }
    .header h1 { margin: 0 0 8px 0; font-size: 26px; }
    .header p { margin: 0; color: #94a3b8; font-size: 14px; }
    .tabs { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
    .tab-btn { flex: 1; min-width: 200px; background: white; border: 2px solid #cbd5e1; padding: 14px; border-radius: 8px; font-size: 15px; font-weight: 700; color: #334155; cursor: pointer; text-align: center; transition: all 0.2s; }
    .tab-btn.active { background: #2563eb; color: white; border-color: #2563eb; }
    .aeropuerto-content { display: none; }
    .aeropuerto-content.active { display: block; }
    .ciudad-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
    .ciudad-header { background: #f8fafc; padding: 14px 18px; font-weight: 700; font-size: 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; }
    .badge { background: #e2e8f0; color: #334155; font-size: 12px; padding: 4px 10px; border-radius: 12px; font-weight: 600; }
    .vuelos-list { padding: 16px; display: none; background: #ffffff; }
    .vuelos-list.open { display: block; }
    .vuelo-item { border: 1px solid #bbf7d0; background: #f0fdf4; border-radius: 8px; padding: 14px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px; }
    .vuelo-tag { background: #dcfce7; color: #166534; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 4px; display: inline-block; margin-bottom: 4px; }
    .vuelo-info { font-size: 15px; font-weight: 800; color: #0f172a; }
    .vuelo-precio { font-size: 22px; font-weight: 900; color: #15803d; text-align: right; }
    .btn-ver { display: inline-block; background: #16a34a; color: white; text-decoration: none; font-size: 12px; font-weight: 700; padding: 6px 14px; border-radius: 6px; margin-top: 4px; }
    .vacio { padding: 30px; text-align: center; color: #64748b; background: white; border-radius: 8px; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Radar de Vuelos Directos Suiza</h1>
      <p>Catálogo centralizado clasificado por aeropuertos y destinos</p>
    </div>

    <div class="tabs">
      <div id="btn-BSL" class="tab-btn" onclick="cambiarAeropuerto('BSL')">📁 Basilea (BSL) (<span id="count-BSL">0</span> chollos)</div>
      <div id="btn-GVA" class="tab-btn" onclick="cambiarAeropuerto('GVA')">📁 Ginebra (GVA) (<span id="count-GVA">0</span> chollos)</div>
      <div id="btn-ZRH" class="tab-btn" onclick="cambiarAeropuerto('ZRH')">📁 Zúrich (ZRH) (<span id="count-ZRH">0</span> chollos)</div>
    </div>

    <div id="panel-BSL" class="aeropuerto-content"></div>
    <div id="panel-GVA" class="aeropuerto-content"></div>
    <div id="panel-ZRH" class="aeropuerto-content"></div>
  </div>

  <script id="datos-vuelos" type="application/json">
    __DATOS_JSON__
  </script>

  <script>
    const todosVuelos = JSON.parse(document.getElementById('datos-vuelos').textContent);

    function construirPaneles() {
      ['BSL', 'GVA', 'ZRH'].forEach(aero => {
        const vuelosAero = todosVuelos.filter(v => v.origen_iata === aero);
        document.getElementById('count-' + aero).innerText = vuelosAero.length;
        const panel = document.getElementById('panel-' + aero);

        if (vuelosAero.length === 0) {
          panel.innerHTML = '<div class="vacio">No hay chollos archivados en este momento para ' + aero + '.</div>';
          return;
        }

        const agrupados = {};
        vuelosAero.forEach(v => {
          const dest = v.destino_nombre + ' (' + v.destino_codigo + ')';
          if (!agrupados[dest]) agrupados[dest] = [];
          agrupados[dest].push(v);
        });

        let html = '';
        for (const [ciudad, lista] of Object.entries(agrupados)) {
          lista.sort((a, b) => a.precio_chf - b.precio_chf);
          html += '<div class="ciudad-card">';
          html += '  <div class="ciudad-header" onclick="this.nextElementSibling.classList.toggle(\\'open\\')">';
          html += '    <span>🏙 ' + ciudad + '</span>';
          html += '    <span class="badge">' + lista.length + ' opciones</span>';
          html += '  </div>';
          html += '  <div class="vuelos-list open">';
          lista.forEach(v => {
            html += '    <div class="vuelo-item">';
            html += '      <div>';
            html += '        <span class="vuelo-tag">' + v.duracion_dias + ' DÍAS · ' + v.fechas + ' · ' + (v.aerolinea || 'Directo') + '</span>';
            html += '        <div class="vuelo-info">🛫 ' + v.origen_nombre + ' ➔ ' + v.destino_nombre + ' (' + v.destino_codigo + ')</div>';
            html += '        <div style="font-size:12px;color:#64748b;">Vuelo Directo · Límite: ' + v.presupuesto_max_chf + ' CHF</div>';
            html += '      </div>';
            html += '      <div style="text-align: right;">';
            html += '        <div class="vuelo-precio">' + v.precio_chf + ' CHF</div>';
            html += '        <a href="' + v.url + '" target="_blank" class="btn-ver">Ver Vuelo</a>';
            html += '      </div>';
            html += '    </div>';
          });
          html += '  </div>';
          html += '</div>';
        }
        panel.innerHTML = html;
      });
    }

    function cambiarAeropuerto(cod) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.aeropuerto-content').forEach(p => p.classList.remove('active'));
      const btn = document.getElementById('btn-' + cod);
      const pnl = document.getElementById('panel-' + cod);
      if (btn && pnl) {
        btn.classList.add('active');
        pnl.classList.add('active');
        window.location.hash = cod;
      }
    }

    window.addEventListener('DOMContentLoaded', () => {
      construirPaneles();
      const hash = window.location.hash.replace('#', '') || 'BSL';
      cambiarAeropuerto(hash);
    });
  </script>
</body>
</html>
"""

def compilar_html(historial):
    html_final = PLANTILLA_HTML.replace("__DATOS_JSON__", json.dumps(historial, ensure_ascii=False))
    with open(ARCHIVO_HTML_SALIDA, "w", encoding="utf-8") as f:
        f.write(html_final)
    print(f"[Portal] '{ARCHIVO_HTML_SALIDA}' generado correctamente.")

# ======================== ENVÍO DE EMAIL CON ENLACES ANCLA ======================== #
def enviar_correo(nuevos, historial_completo, origen="Suiza"):
    if not (SENDER_EMAIL and SENDER_PASSWORD and nuevos):
        return False

    min_precio = min(v["precio_chf"] for v in nuevos)
    asunto = f"✈️ [{origen}] Nuevos Chollos Detectados (desde {min_precio} CHF)"

    bloques_novedades = ""
    for v in sorted(nuevos, key=lambda x: x["precio_chf"])[:6]:
        bloques_novedades += f"""
        <div style="border:1px solid #bbf7d0;background-color:#f0fdf4;border-radius:8px;padding:12px;margin-bottom:10px;">
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td>
                <span style="background-color:#dcfce7;color:#166534;font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;">
                  {v['duracion_dias']} DÍAS · {v['fechas']} · {v.get('aerolinea', 'Directo')}
                </span>
                <div style="font-size:15px;font-weight:800;color:#0f172a;margin-top:6px;">
                  🛫 {v['origen_nombre']} ➔ {v['destino_nombre']} ({v['destino_codigo']})
                </div>
                <div style="font-size:12px;color:#475569;">Vuelo Directo · Límite: {v['presupuesto_max_chf']} CHF</div>
              </td>
              <td style="text-align:right;width:110px;">
                <div style="font-size:20px;font-weight:900;color:#15803d;">{v['precio_chf']} CHF</div>
                <a href="{v['url']}" style="display:inline-block;margin-top:6px;background-color:#16a34a;color:#fff;text-decoration:none;font-size:11px;font-weight:700;padding:5px 12px;border-radius:4px;">Ver Vuelo</a>
              </td>
            </tr>
          </table>
        </div>
        """

    por_aeropuerto = defaultdict(list)
    for v in historial_completo:
        por_aeropuerto[v.get("origen_iata", "Otros")].append(v)

    filas_carpetas = ""
    for aero in ORDEN_AEROPUERTOS:
        cantidad = len(por_aeropuerto.get(aero, []))
        url_carpeta = f"{PAGES_URL}#{aero}" if PAGES_URL else f"#{aero}"
        filas_carpetas += f"""
        <tr style="border-top:1px solid #e2e8f0;">
          <td style="padding:10px 0;font-size:13px;color:#1e293b;font-weight:600;">
            🛫 Salidas desde {NOMBRES_AEROPUERTOS.get(aero, aero)}
            <div style="font-size:11px;color:#64748b;font-weight:normal;">({cantidad} chollos archivados)</div>
          </td>
          <td style="padding:10px 0;text-align:right;">
            <a href="{url_carpeta}" target="_blank" style="display:inline-block;background-color:#2563eb;color:#ffffff;text-decoration:none;font-size:11px;font-weight:700;padding:6px 12px;border-radius:4px;">
              📁 Abrir Carpeta
            </a>
          </td>
        </tr>
        """

    html = f"""
    <div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background-color:#f8fafc;padding:20px;color:#0f172a;">
      <div style="background-color:#0f172a;color:#fff;padding:18px;border-radius:8px 8px 0 0;text-align:center;">
        <h2 style="margin:0 0 6px 0;font-size:20px;">Radar de Vuelos Suiza</h2>
        <p style="margin:0;color:#94a3b8;font-size:13px;">Nueva alerta encontrada desde Suiza</p>
      </div>

      <div style="background-color:#fff;padding:20px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
        <h3 style="margin-top:0;font-size:14px;color:#16a34a;text-transform:uppercase;">🟢 Chollos Recientes Detectados</h3>
        {bloques_novedades}
      </div>

      <div style="background-color:#f1f5f9;padding:20px;border:1px solid #e2e8f0;border-radius:0 0 8px 8px;">
        <h3 style="margin-top:0;font-size:13px;color:#475569;text-transform:uppercase;">📁 Catálogo Activo por Aeropuerto de Salida</h3>
        <div style="background-color:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px;">
          <table style="width:100%;border-collapse:collapse;">
            {filas_carpetas}
          </table>
        </div>
      </div>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = f"Radar Vuelos Suiza <{SENDER_EMAIL}>"
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
            s.login(SENDER_EMAIL, SENDER_PASSWORD)
            s.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        print(f"[Email] Alerta enviada con éxito a {RECIPIENT_EMAIL}")
        return True
    except Exception as e:
        print(f"[Email Error] Error al despachar correo: {e}")
        return False

# ======================== EJECUCIÓN PRINCIPAL ======================== #
def main():
    t0 = time.time()
    historial = cargar_historial()
    
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    historial = [v for v in historial if v.get("fecha_ida", "") >= hoy_str]
    ids_registrados = {v.get("id") for v in historial if "id" in v}
    
    nuevos_totales = []

    for aero in ORDEN_AEROPUERTOS:
        print(f"[Escaneo] Analizando {aero}...")
        encontrados_ryanair = rastrear_ryanair(origen=aero, dias_horizonte=30)
        encontrados_resto = rastrear_todas_aerolineas_http(origen=aero)

        for v in encontrados_ryanair + encontrados_resto:
            if v["id"] not in ids_registrados:
                nuevos_totales.append(v)
                historial.append(v)
                ids_registrados.add(v["id"])

    print(f"[Resultado] Total encontrados: {len(nuevos_totales)} chollos nuevos. Tiempo transcurrido: {round(time.time() - t0, 2)}s")

    if nuevos_totales:
        enviar_correo(nuevos_totales, historial, origen="Suiza")

    guardar_historial(historial)
    compilar_html(historial)

if __name__ == "__main__":
    main()
