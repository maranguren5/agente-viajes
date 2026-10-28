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
FORZAR_CORREO = os.environ.get("FORZAR_CORREO", "false").lower() == "true"

GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "")
if os.environ.get("PAGES_URL"):
    PAGES_URL = os.environ.get("PAGES_URL").rstrip("/")
elif GITHUB_REPOSITORY and "/" in GITHUB_REPOSITORY:
    owner, repo = GITHUB_REPOSITORY.split("/", 1)
    PAGES_URL = f"https://{owner}.github.io/{repo}"
else:
    PAGES_URL = ""

DIR_DATA = "data"
ARCHIVO_HISTORIAL = os.path.join(DIR_DATA, "historial_vuelos.json")
ARCHIVO_CURSOR = os.path.join(DIR_DATA, "estado_cursor.json")
ARCHIVO_HTML_SALIDA = "index.html"

PRESUPUESTO_TOTAL_MAX_CHF = 100.0

# Tarifas de conexion terrestre ida y vuelta desde Lucerna (Halbtax aplicado)
AEROPUERTOS_CONFIG = {
    "ZRH": {"nombre": "Zúrich (ZRH)", "transfer_chf": 26.0},
    "BSL": {"nombre": "Basilea (BSL)", "transfer_chf": 32.0},
    "BGY": {"nombre": "Milán Bérgamo (BGY)", "transfer_chf": 42.0},
    "MXP": {"nombre": "Milán Malpensa (MXP)", "transfer_chf": 42.0},
    "GVA": {"nombre": "Ginebra (GVA)", "transfer_chf": 70.0}
}
ORDEN_AEROPUERTOS = ["ZRH", "BSL", "BGY", "MXP", "GVA"]

# Destinos principales con conexion directa
DESTINOS_POR_AEROPUERTO = {
    "ZRH": [
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "ALC", "nombre": "Alicante"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "BCN", "nombre": "Barcelona"},
        {"codigo": "MAD", "nombre": "Madrid"},
        {"codigo": "BER", "nombre": "Berlín"},
        {"codigo": "LON", "nombre": "Londres"},
        {"codigo": "VIE", "nombre": "Viena"}
    ],
    "BSL": [
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "FAO", "nombre": "Faro"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "ALC", "nombre": "Alicante"},
        {"codigo": "AGP", "nombre": "Málaga"},
        {"codigo": "VLC", "nombre": "Valencia"},
        {"codigo": "MAD", "nombre": "Madrid"},
        {"codigo": "BCN", "nombre": "Barcelona"},
        {"codigo": "LON", "nombre": "Londres"},
        {"codigo": "DUB", "nombre": "Dublín"},
        {"codigo": "EDI", "nombre": "Edimburgo"},
        {"codigo": "BUD", "nombre": "Budapest"},
        {"codigo": "KRK", "nombre": "Cracovia"},
        {"codigo": "WAW", "nombre": "Varsovia"},
        {"codigo": "BER", "nombre": "Berlín"},
        {"codigo": "HAM", "nombre": "Hamburgo"}
    ],
    "BGY": [
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "VLC", "nombre": "Valencia"},
        {"codigo": "AGP", "nombre": "Málaga"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "SEV", "nombre": "Sevilla"},
        {"codigo": "ATH", "nombre": "Atenas"},
        {"codigo": "LON", "nombre": "Londres"},
        {"codigo": "DUB", "nombre": "Dublín"}
    ],
    "MXP": [
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "BCN", "nombre": "Barcelona"},
        {"codigo": "MAD", "nombre": "Madrid"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "LON", "nombre": "Londres"}
    ],
    "GVA": [
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "BCN", "nombre": "Barcelona"},
        {"codigo": "MAD", "nombre": "Madrid"},
        {"codigo": "LON", "nombre": "Londres"}
    ]
}

# ======================== PERSISTENCIA LOCAL (COSTE 0) ======================== #
def cargar_json(ruta, defecto):
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Error] Fallo al cargar {ruta}: {e}")
    return defecto

def guardar_json(ruta, datos):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

def obtener_siguiente_tarea():
    estado = cargar_json(ARCHIVO_CURSOR, {"aero_idx": 0, "ciudad_idx": 0})
    aero_idx = estado.get("aero_idx", 0) % len(ORDEN_AEROPUERTOS)
    aero_actual = ORDEN_AEROPUERTOS[aero_idx]

    lista_ciudades = DESTINOS_POR_AEROPUERTO.get(aero_actual, [])
    if not lista_ciudades:
        aero_idx = (aero_idx + 1) % len(ORDEN_AEROPUERTOS)
        aero_actual = ORDEN_AEROPUERTOS[aero_idx]
        lista_ciudades = DESTINOS_POR_AEROPUERTO[aero_actual]
        estado["ciudad_idx"] = 0

    ciudad_idx = estado.get("ciudad_idx", 0) % len(lista_ciudades)
    ciudad_actual = lista_ciudades[ciudad_idx]

    siguiente_ciudad = ciudad_idx + 1
    if siguiente_ciudad >= len(lista_ciudades):
        estado["aero_idx"] = (aero_idx + 1) % len(ORDEN_AEROPUERTOS)
        estado["ciudad_idx"] = 0
    else:
        estado["aero_idx"] = aero_idx
        estado["ciudad_idx"] = siguiente_ciudad

    guardar_json(ARCHIVO_CURSOR, estado)
    return aero_actual, ciudad_actual

# ======================== MOTOR DE CONSULTA MULTIAEROLÍNEA ======================== #
def consultar_vuelos_google(session, origen, destino_cod, f_ida, f_vta):
    """
    Realiza la consulta al servicio de vuelos de Google emulando el cliente web suizo.
    Extrae la tarifa verificada de ida y vuelta en francos suizos (CHF).
    """
    url = f"https://www.google.com/travel/flights?q=Round-trip%20flights%20from%20{origen}%20to%20{destino_cod}%20departing%20{f_ida}%20returning%20{f_vta}&curr=CHF&hl=es-CH&gl=ch"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept-Language": "es-CH,es;q=0.9,de-CH;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache"
    }

    try:
        r = session.get(url, headers=headers, timeout=9)
        if r.status_code != 200:
            return None, "Desconocida", url

        texto = r.text

        # 1. Extraccion de la aerolinea principal mencionada en la tarjeta del itinerario
        aerolinea = "Vuelo Directo"
        aerolineas_clave = [
            ("EasyJet", "easyjet"),
            ("SWISS", "swiss"),
            ("Ryanair", "ryanair"),
            ("Wizz Air", "wizz"),
            ("Iberia", "iberia"),
            ("TAP Air Portugal", "tap"),
            ("Vueling", "vueling"),
            ("Lufthansa", "lufthansa")
        ]
        texto_lower = texto.lower()
        for nombre_oficial, palabra_clave in aerolineas_clave:
            if palabra_clave in texto_lower:
                aerolinea = nombre_oficial
                break

        # 2. Localizacion de la tarifa total de ida y vuelta en CHF dentro del flujo de datos
        # Se buscan coincidencias con el patron de moneda suiza (CHF o Fr.) seguido del valor numerico
        patrones = [
            r'data-fare=["\'](\d+)["\']',
            r'(?:CHF|Fr\.)\s*([0-9]{1,3}(?:[\.,][0-9]{2})?)',
            r'([0-9]{1,3}(?:[\.,][0-9]{2})?)\s*(?:CHF|Fr\.)',
            r'\[null,null,null,null,null,null,\[\[(\d+),'
        ]

        valores_detectados = []
        for patron in patrones:
            coincidencias = re.findall(patron, texto)
            for item in coincidencias:
                limpio = str(item).replace(",", ".").strip()
                try:
                    val = float(limpio)
                    # Filtro de sensatez: se ignoran importes menores a 15 CHF (tasas o seguros)
                    # y superiores a 350 CHF
                    if 15.0 <= val <= 350.0:
                        valores_detectados.append(val)
                except ValueError:
                    continue

        if valores_detectados:
            precio_minimo = min(valores_detectados)
            return precio_minimo, aerolinea, url

    except Exception as e:
        print(f"[Aviso] Falla de conexion para {origen}->{destino_cod}: {e}")

    return None, "Desconocida", url

def rastrear_escapadas_multiaerolinea(session, origen, destino, dias_horizonte=45):
    vuelos_validos = []
    hoy = datetime.now()
    cod_dest = destino["codigo"]
    nom_dest = destino["nombre"]
    transfer_lucerna = AEROPUERTOS_CONFIG[origen]["transfer_chf"]
    tope_vuelo_permitido = round(PRESUPUESTO_TOTAL_MAX_CHF - transfer_lucerna, 2)

    # Identificacion de fines de semana de 4 dias (Jueves a Domingo y Viernes a Lunes)
    combinaciones = []
    for d in range(1, dias_horizonte):
        f_ida_dt = hoy + timedelta(days=d)
        dia_semana = f_ida_dt.weekday()  # 3 = Jueves, 4 = Viernes

        if dia_semana in [3, 4]:
            f_vta_dt = f_ida_dt + timedelta(days=3)
            etiqueta = "Jueves a Domingo" if dia_semana == 3 else "Viernes a Lunes"
            combinaciones.append((
                f_ida_dt.strftime("%Y-%m-%d"),
                f_vta_dt.strftime("%Y-%m-%d"),
                etiqueta
            ))

    # Se procesa un lote concentrado de los proximos 4 fines de semana
    for f_ida_str, f_vta_str, etiqueta_patron in combinaciones[:4]:
        precio_vuelo, aerolinea, url_directa = consultar_vuelos_google(
            session, origen, cod_dest, f_ida_str, f_vta_str
        )

        if precio_vuelo is not None:
            coste_total_viaje = round(precio_vuelo + transfer_lucerna, 2)

            # Validacion inquebrantable del presupuesto global
            if coste_total_viaje <= PRESUPUESTO_TOTAL_MAX_CHF:
                v_id = f"{origen}-{cod_dest}-{f_ida_str}-{f_vta_str}-{int(coste_total_viaje)}"
                vuelos_validos.append({
                    "id": v_id,
                    "origen_iata": origen,
                    "origen_nombre": AEROPUERTOS_CONFIG[origen]["nombre"],
                    "destino_codigo": cod_dest,
                    "destino_nombre": nom_dest,
                    "patron": etiqueta_patron,
                    "precio_vuelo_chf": precio_vuelo,
                    "coste_transfer_chf": transfer_lucerna,
                    "coste_total_chf": coste_total_viaje,
                    "tope_vuelo_max": tope_vuelo_permitido,
                    "fechas": f"{f_ida_str} al {f_vta_str}",
                    "fecha_ida": f_ida_str,
                    "fecha_vuelta": f_vta_str,
                    "aerolinea": aerolinea,
                    "url": url_directa,
                    "fecha_deteccion": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                })

    return vuelos_validos

# ======================== COMPILADOR HTML (GITHUB PAGES) ======================== #
PLANTILLA_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Radar de Escapadas Fin de Semana (Máx 100 CHF)</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background-color: #f1f5f9; color: #0f172a; margin: 0; padding: 20px; }
    .container { max-width: 960px; margin: 0 auto; }
    .header { background: #0f172a; color: white; padding: 24px; border-radius: 12px; margin-bottom: 24px; text-align: center; }
    .header h1 { margin: 0 0 8px 0; font-size: 24px; }
    .header p { margin: 0; color: #94a3b8; font-size: 14px; }
    .tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
    .tab-btn { flex: 1; min-width: 160px; background: white; border: 2px solid #cbd5e1; padding: 12px; border-radius: 8px; font-size: 14px; font-weight: 700; color: #334155; cursor: pointer; text-align: center; transition: all 0.2s; }
    .tab-btn.active { background: #2563eb; color: white; border-color: #2563eb; }
    .aeropuerto-content { display: none; }
    .aeropuerto-content.active { display: block; }
    .ciudad-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
    .ciudad-header { background: #f8fafc; padding: 14px 18px; font-weight: 700; font-size: 15px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; }
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
      <h1>Radar Escapadas Fin de Semana (Multiaerolínea)</h1>
      <p>Puerta a puerta desde Lucerna · Presupuesto Total &le; 100 CHF (Vuelo + Tren Halbtax)</p>
    </div>

    <div class="tabs">
      <div id="btn-ZRH" class="tab-btn" onclick="cambiarAeropuerto('ZRH')">📁 Zúrich (<span id="count-ZRH">0</span>)</div>
      <div id="btn-BSL" class="tab-btn" onclick="cambiarAeropuerto('BSL')">📁 Basilea (<span id="count-BSL">0</span>)</div>
      <div id="btn-BGY" class="tab-btn" onclick="cambiarAeropuerto('BGY')">📁 M. Bérgamo (<span id="count-BGY">0</span>)</div>
      <div id="btn-MXP" class="tab-btn" onclick="cambiarAeropuerto('MXP')">📁 M. Malpensa (<span id="count-MXP">0</span>)</div>
      <div id="btn-GVA" class="tab-btn" onclick="cambiarAeropuerto('GVA')">📁 Ginebra (<span id="count-GVA">0</span>)</div>
    </div>

    <div id="panel-ZRH" class="aeropuerto-content"></div>
    <div id="panel-BSL" class="aeropuerto-content"></div>
    <div id="panel-BGY" class="aeropuerto-content"></div>
    <div id="panel-MXP" class="aeropuerto-content"></div>
    <div id="panel-GVA" class="aeropuerto-content"></div>
  </div>

  <script id="datos-vuelos" type="application/json">
    __DATOS_JSON__
  </script>

  <script>
    const todosVuelos = JSON.parse(document.getElementById('datos-vuelos').textContent);

    function construirPaneles() {
      ['ZRH', 'BSL', 'BGY', 'MXP', 'GVA'].forEach(aero => {
        const vuelosAero = todosVuelos.filter(v => v.origen_iata === aero);
        document.getElementById('count-' + aero).innerText = vuelosAero.length;
        const panel = document.getElementById('panel-' + aero);

        if (vuelosAero.length === 0) {
          panel.innerHTML = '<div class="vacio">No hay escapadas archivadas por debajo de 100 CHF total para ' + aero + '.</div>';
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
          lista.sort((a, b) => a.coste_total_chf - b.coste_total_chf);
          html += '<div class="ciudad-card">';
          html += '  <div class="ciudad-header" onclick="this.nextElementSibling.classList.toggle(\\'open\\')">';
          html += '    <span>🏙 ' + ciudad + '</span>';
          html += '    <span class="badge">' + lista.length + ' opciones</span>';
          html += '  </div>';
          html += '  <div class="vuelos-list open">';
          lista.forEach(v => {
            html += '    <div class="vuelo-item">';
            html += '      <div>';
            html += '        <span class="vuelo-tag">' + v.patron + ' · ' + v.fechas + ' · ' + (v.aerolinea || 'Directo') + '</span>';
            html += '        <div class="vuelo-info">🛫 ' + v.origen_nombre + ' ➔ ' + v.destino_nombre + '</div>';
            html += '        <div style="font-size:12px;color:#475569;margin-top:2px;">Vuelo: ' + v.precio_vuelo_chf + ' CHF + Tren Lucerna: ' + v.coste_transfer_chf + ' CHF</div>';
            html += '      </div>';
            html += '      <div style="text-align: right;">';
            html += '        <div class="vuelo-precio">' + v.coste_total_chf + ' CHF</div>';
            html += '        <div style="font-size:11px;color:#64748b;">TOTAL VIAJE</div>';
            html += '        <a href="' + v.url + '" target="_blank" class="btn-ver">Ver en Google Flights</a>';
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
      const hash = window.location.hash.replace('#', '') || 'ZRH';
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

# ======================== ENVÍO DE EMAIL CON DESGLOSE PUERTA A PUERTA ======================== #
def enviar_correo(vuelos_a_enviar, historial_completo, origen, destino_nombre):
    if not (SENDER_EMAIL and SENDER_PASSWORD and vuelos_a_enviar):
        return False

    min_total = min(v["coste_total_chf"] for v in vuelos_a_enviar)
    asunto = f"✈️ [{origen}] Escapada a {destino_nombre} por {min_total} CHF (Todo Incluido)"

    bloques_novedades = ""
    for v in sorted(vuelos_a_enviar, key=lambda x: x["coste_total_chf"])[:6]:
        bloques_novedades += f"""
        <div style="border:1px solid #bbf7d0;background-color:#f0fdf4;border-radius:8px;padding:12px;margin-bottom:10px;">
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td>
                <span style="background-color:#dcfce7;color:#166534;font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;">
                  {v['patron']} · {v['fechas']} (4 DÍAS) · {v.get('aerolinea', 'Directo')}
                </span>
                <div style="font-size:15px;font-weight:800;color:#0f172a;margin-top:6px;">
                  🛫 {v['origen_nombre']} ➔ {v['destino_nombre']} ({v['destino_codigo']})
                </div>
                <div style="font-size:12px;color:#475569;margin-top:3px;">
                  ✈️ Vuelo verificado: <strong>{v['precio_vuelo_chf']} CHF</strong><br>
                  🚆 Tren Halbtax Lucerna: <strong>{v['coste_transfer_chf']} CHF</strong>
                </div>
              </td>
              <td style="text-align:right;width:120px;">
                <div style="font-size:22px;font-weight:900;color:#15803d;">{v['coste_total_chf']} CHF</div>
                <div style="font-size:10px;color:#64748b;margin-bottom:4px;">PUERTA A PUERTA</div>
                <a href="{v['url']}" target="_blank" style="display:inline-block;background-color:#16a34a;color:#fff;text-decoration:none;font-size:11px;font-weight:700;padding:5px 12px;border-radius:4px;">Ver Oferta</a>
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
        url_carpeta = f"{PAGES_URL}/#{aero}" if PAGES_URL else f"#{aero}"
        nombre_aero = AEROPUERTOS_CONFIG[aero]["nombre"]
        transfer = AEROPUERTOS_CONFIG[aero]["transfer_chf"]
        filas_carpetas += f"""
        <tr style="border-top:1px solid #e2e8f0;">
          <td style="padding:10px 0;font-size:13px;color:#1e293b;font-weight:600;">
            🛫 {nombre_aero}
            <div style="font-size:11px;color:#64748b;font-weight:normal;">Tren Lucerna: {transfer} CHF | {cantidad} escapadas &le; 100 CHF</div>
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
        <h2 style="margin:0 0 6px 0;font-size:20px;">Radar Escapadas Lucerna (Multiaerolínea)</h2>
        <p style="margin:0;color:#94a3b8;font-size:13px;">Fin de semana (4 días) · Presupuesto Total &le; 100 CHF</p>
      </div>

      <div style="background-color:#fff;padding:20px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
        <h3 style="margin-top:0;font-size:14px;color:#16a34a;text-transform:uppercase;">🟢 Oferta Confirmada</h3>
        {bloques_novedades}
      </div>

      <div style="background-color:#f1f5f9;padding:20px;border:1px solid #e2e8f0;border-radius:0 0 8px 8px;">
        <h3 style="margin-top:0;font-size:13px;color:#475569;text-transform:uppercase;">📁 Catálogo Activo por Aeropuerto</h3>
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
        print(f"[Email Error] Error al enviar correo: {e}")
        return False

# ======================== EJECUCIÓN PRINCIPAL ======================== #
def main():
    t0 = time.time()
    historial = cargar_json(ARCHIVO_HISTORIAL, [])
    
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    historial = [v for v in historial if v.get("fecha_ida", "") >= hoy_str]
    ids_registrados = {v.get("id") for v in historial if "id" in v}
    
    aero_actual, ciudad_actual = obtener_siguiente_tarea()
    print(f"[Cola] Procesando ruta: {aero_actual} -> {ciudad_actual['nombre']} ({ciudad_actual['codigo']})...")

    with requests.Session() as s:
        encontrados = rastrear_escapadas_multiaerolinea(s, aero_actual, ciudad_actual, dias_horizonte=45)

    nuevos = []
    for v in encontrados:
        if v["id"] not in ids_registrados:
            nuevos.append(v)
            historial.append(v)
            ids_registrados.add(v["id"])

    print(f"[Resultado] {len(encontrados)} escapadas encontradas ({len(nuevos)} nuevas en catálogo).")

    if nuevos:
        enviar_correo(nuevos, historial, origen=aero_actual, destino_nombre=ciudad_actual["nombre"])
    elif FORZAR_CORREO and historial:
        print("[Prueba] Forzando correo con datos del catálogo...")
        enviar_correo(historial[:6], historial, origen=aero_actual, destino_nombre=ciudad_actual["nombre"])

    guardar_json(ARCHIVO_HISTORIAL, historial)
    compilar_html(historial)
    print(f"[Completado] Tiempo total: {round(time.time() - t0, 2)}s")

if __name__ == "__main__":
    main()
