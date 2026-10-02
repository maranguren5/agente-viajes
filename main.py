import os
import re
import json
import time
import random
import smtplib
from collections import defaultdict
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from flask import Flask, jsonify
from flask_cors import CORS
from google.cloud import storage
from playwright.sync_api import sync_playwright

# ======================== CONFIGURACIÓN Y CREDENCIALES ======================== #
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECIPIENT_EMAIL = os.environ.get("RECIPIENT_EMAIL", SENDER_EMAIL)
BUCKET_HISTORIAL = os.environ.get("BUCKET_HISTORIAL")

ARCHIVO_HISTORIAL = "historial_vuelos.json"
ARCHIVO_ESTADO = "estado_cursor.json"

# Freno de seguridad para no superar los 130s de Cloud Run
TIEMPO_MAXIMO_SEGUNDOS = 105.0

# Orden estricto: Basilea -> Ginebra -> Zúrich
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

# ==================== CENSO OFICIAL DE VUELOS DIRECTOS EUROPEOS ==================== #
# Sin España peninsular (mantiene Baleares PMI/IBZ/MAH). Fuente oficial aeroportuaria.
DESTINOS_DIRECTOS_POR_AEROPUERTO = {
    "BSL": [
        {"codigo": "LON", "nombre": "Londres"},
        {"codigo": "PRN", "nombre": "Pristina"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "FAO", "nombre": "Faro"},
        {"codigo": "BUD", "nombre": "Budapest"},
        {"codigo": "KRK", "nombre": "Cracovia"},
        {"codigo": "WAW", "nombre": "Varsovia"},
        {"codigo": "WRO", "nombre": "Breslavia"},
        {"codigo": "BER", "nombre": "Berlín"},
        {"codigo": "HAM", "nombre": "Hamburgo"},
        {"codigo": "MUC", "nombre": "Múnich"},
        {"codigo": "FRA", "nombre": "Fráncfort"},
        {"codigo": "VIE", "nombre": "Viena"},
        {"codigo": "AMS", "nombre": "Ámsterdam"},
        {"codigo": "CPH", "nombre": "Copenhague"},
        {"codigo": "OSL", "nombre": "Oslo"},
        {"codigo": "ZAG", "nombre": "Zagreb"},
        {"codigo": "SPU", "nombre": "Split"},
        {"codigo": "DBV", "nombre": "Dubrovnik"},
        {"codigo": "ZAD", "nombre": "Zadar"},
        {"codigo": "PRG", "nombre": "Praga"},
        {"codigo": "OTP", "nombre": "Bucarest"},
        {"codigo": "CLJ", "nombre": "Cluj-Napoca"},
        {"codigo": "IAS", "nombre": "Iași"},
        {"codigo": "SOF", "nombre": "Sofía"},
        {"codigo": "SKP", "nombre": "Skopie"},
        {"codigo": "BEG", "nombre": "Belgrado"},
        {"codigo": "TIA", "nombre": "Tirana"},
        {"codigo": "NCE", "nombre": "Niza"},
        {"codigo": "BOD", "nombre": "Burdeos"},
        {"codigo": "TLS", "nombre": "Toulouse"},
        {"codigo": "NTE", "nombre": "Nantes"},
        {"codigo": "CDG", "nombre": "París"},
        {"codigo": "ROM", "nombre": "Roma"},
        {"codigo": "VCE", "nombre": "Venecia"},
        {"codigo": "NAP", "nombre": "Nápoles"},
        {"codigo": "CTA", "nombre": "Catania"},
        {"codigo": "PMO", "nombre": "Palermo"},
        {"codigo": "BRI", "nombre": "Bari"},
        {"codigo": "BDS", "nombre": "Brindisi"},
        {"codigo": "CAG", "nombre": "Cagliari"},
        {"codigo": "OLB", "nombre": "Olbia"},
        {"codigo": "MLA", "nombre": "Malta"},
        {"codigo": "ATH", "nombre": "Atenas"},
        {"codigo": "SKG", "nombre": "Tesalónica"},
        {"codigo": "HER", "nombre": "Heraclión"},
        {"codigo": "CFU", "nombre": "Corfú"},
        {"codigo": "DUB", "nombre": "Dublín"},
        {"codigo": "EDI", "nombre": "Edimburgo"},
        {"codigo": "MAN", "nombre": "Mánchester"},
        {"codigo": "BRS", "nombre": "Bristol"},
        {"codigo": "LCA", "nombre": "Lárnaca"}
    ],
    "GVA": [
        {"codigo": "LON", "nombre": "Londres"},
        {"codigo": "MAN", "nombre": "Mánchester"},
        {"codigo": "EDI", "nombre": "Edimburgo"},
        {"codigo": "BRS", "nombre": "Bristol"},
        {"codigo": "DUB", "nombre": "Dublín"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "FAO", "nombre": "Faro"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "IBZ", "nombre": "Ibiza"},
        {"codigo": "NCE", "nombre": "Niza"},
        {"codigo": "BOD", "nombre": "Burdeos"},
        {"codigo": "NTE", "nombre": "Nantes"},
        {"codigo": "CDG", "nombre": "París"},
        {"codigo": "AMS", "nombre": "Ámsterdam"},
        {"codigo": "BRU", "nombre": "Bruselas"},
        {"codigo": "LUX", "nombre": "Luxemburgo"},
        {"codigo": "FRA", "nombre": "Fráncfort"},
        {"codigo": "MUC", "nombre": "Múnich"},
        {"codigo": "BER", "nombre": "Berlín"},
        {"codigo": "HAM", "nombre": "Hamburgo"},
        {"codigo": "VIE", "nombre": "Viena"},
        {"codigo": "PRG", "nombre": "Praga"},
        {"codigo": "BUD", "nombre": "Budapest"},
        {"codigo": "WAW", "nombre": "Varsovia"},
        {"codigo": "KRK", "nombre": "Cracovia"},
        {"codigo": "CPH", "nombre": "Copenhague"},
        {"codigo": "OSL", "nombre": "Oslo"},
        {"codigo": "ARN", "nombre": "Estocolmo"},
        {"codigo": "HEL", "nombre": "Helsinki"},
        {"codigo": "ROM", "nombre": "Roma"},
        {"codigo": "VCE", "nombre": "Venecia"},
        {"codigo": "NAP", "nombre": "Nápoles"},
        {"codigo": "CTA", "nombre": "Catania"},
        {"codigo": "PMO", "nombre": "Palermo"},
        {"codigo": "OLB", "nombre": "Olbia"},
        {"codigo": "CAG", "nombre": "Cagliari"},
        {"codigo": "BRI", "nombre": "Bari"},
        {"codigo": "MLA", "nombre": "Malta"},
        {"codigo": "ATH", "nombre": "Atenas"},
        {"codigo": "HER", "nombre": "Heraclión"},
        {"codigo": "SKP", "nombre": "Skopie"},
        {"codigo": "PRN", "nombre": "Pristina"},
        {"codigo": "BEG", "nombre": "Belgrado"},
        {"codigo": "TIA", "nombre": "Tirana"},
        {"codigo": "OTP", "nombre": "Bucarest"},
        {"codigo": "SOF", "nombre": "Sofía"}
    ],
    "ZRH": [
        {"codigo": "LON", "nombre": "Londres"},
        {"codigo": "MAN", "nombre": "Mánchester"},
        {"codigo": "EDI", "nombre": "Edimburgo"},
        {"codigo": "BHX", "nombre": "Birmingham"},
        {"codigo": "DUB", "nombre": "Dublín"},
        {"codigo": "BER", "nombre": "Berlín"},
        {"codigo": "HAM", "nombre": "Hamburgo"},
        {"codigo": "DUS", "nombre": "Düsseldorf"},
        {"codigo": "FRA", "nombre": "Fráncfort"},
        {"codigo": "MUC", "nombre": "Múnich"},
        {"codigo": "HAJ", "nombre": "Hannover"},
        {"codigo": "VIE", "nombre": "Viena"},
        {"codigo": "AMS", "nombre": "Ámsterdam"},
        {"codigo": "BRU", "nombre": "Bruselas"},
        {"codigo": "CDG", "nombre": "París"},
        {"codigo": "NCE", "nombre": "Niza"},
        {"codigo": "BOD", "nombre": "Burdeos"},
        {"codigo": "NTE", "nombre": "Nantes"},
        {"codigo": "LIS", "nombre": "Lisboa"},
        {"codigo": "OPO", "nombre": "Oporto"},
        {"codigo": "FAO", "nombre": "Faro"},
        {"codigo": "PMI", "nombre": "Palma de Mallorca"},
        {"codigo": "IBZ", "nombre": "Ibiza"},
        {"codigo": "ROM", "nombre": "Roma"},
        {"codigo": "MIL", "nombre": "Milán"},
        {"codigo": "VCE", "nombre": "Venecia"},
        {"codigo": "NAP", "nombre": "Nápoles"},
        {"codigo": "CTA", "nombre": "Catania"},
        {"codigo": "PMO", "nombre": "Palermo"},
        {"codigo": "BLQ", "nombre": "Bolonia"},
        {"codigo": "FLR", "nombre": "Florencia"},
        {"codigo": "BRI", "nombre": "Bari"},
        {"codigo": "BDS", "nombre": "Brindisi"},
        {"codigo": "OLB", "nombre": "Olbia"},
        {"codigo": "CAG", "nombre": "Cagliari"},
        {"codigo": "MLA", "nombre": "Malta"},
        {"codigo": "PRG", "nombre": "Praga"},
        {"codigo": "BUD", "nombre": "Budapest"},
        {"codigo": "WAW", "nombre": "Varsovia"},
        {"codigo": "KRK", "nombre": "Cracovia"},
        {"codigo": "WRO", "nombre": "Breslavia"},
        {"codigo": "GDN", "nombre": "Gdansk"},
        {"codigo": "ZAG", "nombre": "Zagreb"},
        {"codigo": "SPU", "nombre": "Split"},
        {"codigo": "DBV", "nombre": "Dubrovnik"},
        {"codigo": "LJU", "nombre": "Liubliana"},
        {"codigo": "BEG", "nombre": "Belgrado"},
        {"codigo": "SOF", "nombre": "Sofía"},
        {"codigo": "OTP", "nombre": "Bucarest"},
        {"codigo": "CLJ", "nombre": "Cluj-Napoca"},
        {"codigo": "SKP", "nombre": "Skopie"},
        {"codigo": "PRN", "nombre": "Pristina"},
        {"codigo": "TIA", "nombre": "Tirana"},
        {"codigo": "CPH", "nombre": "Copenhague"},
        {"codigo": "OSL", "nombre": "Oslo"},
        {"codigo": "ARN", "nombre": "Estocolmo"},
        {"codigo": "GOT", "nombre": "Gotemburgo"},
        {"codigo": "HEL", "nombre": "Helsinki"},
        {"codigo": "RIX", "nombre": "Riga"},
        {"codigo": "VNO", "nombre": "Vilna"},
        {"codigo": "TLL", "nombre": "Tallin"},
        {"codigo": "ATH", "nombre": "Atenas"},
        {"codigo": "SKG", "nombre": "Tesalónica"},
        {"codigo": "HER", "nombre": "Heraclión"},
        {"codigo": "LCA", "nombre": "Lárnaca"}
    ]
}


# ======================== PERSISTENCIA GCS ======================== #
def obtener_blob(nombre_archivo):
    if not BUCKET_HISTORIAL:
        return None
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_HISTORIAL)
        return bucket.blob(nombre_archivo)
    except Exception as e:
        print(f"[GCS Error] Conexión fallida: {e}")
        return None

def cargar_json_storage(nombre_archivo, defecto):
    blob = obtener_blob(nombre_archivo)
    if blob and blob.exists():
        try:
            return json.loads(blob.download_as_text())
        except Exception:
            pass
    return defecto

def guardar_json_storage(nombre_archivo, datos):
    blob = obtener_blob(nombre_archivo)
    if blob:
        try:
            blob.upload_from_string(json.dumps(datos, ensure_ascii=False, indent=2), content_type="application/json")
        except Exception as e:
            print(f"[GCS Error] Error guardando {nombre_archivo}: {e}")


# ======================== GESTIÓN DE COLA SECUENCIAL ======================== #
def sincronizar_cola():
    estado = cargar_json_storage(ARCHIVO_ESTADO, {
        "aeropuerto_idx": 0,
        "ciudades_pendientes": [],
        "ciudades_completadas_aeropuerto": [],
        "tarea_en_curso": None
    })

    # Si hay una tarea a medio hacer (por corte de 105s)
    if estado.get("tarea_en_curso"):
        tarea = estado["tarea_en_curso"]
        return tarea, estado

    # Si no quedan ciudades en el aeropuerto en curso, avanzar al siguiente
    if not estado.get("ciudades_pendientes"):
        if estado.get("ciudades_completadas_aeropuerto"):
            estado["aeropuerto_idx"] = (estado.get("aeropuerto_idx", 0) + 1) % len(ORDEN_AEROPUERTOS)
            estado["ciudades_completadas_aeropuerto"] = []

        aeropuerto_actual = ORDEN_AEROPUERTOS[estado["aeropuerto_idx"]]
        # Cargamos el catálogo completo real de ese aeropuerto
        estado["ciudades_pendientes"] = list(DESTINOS_DIRECTOS_POR_AEROPUERTO[aeropuerto_actual])
        guardar_json_storage(ARCHIVO_ESTADO, estado)

    aeropuerto_actual = ORDEN_AEROPUERTOS[estado["aeropuerto_idx"]]
    siguiente_ciudad = estado["ciudades_pendientes"].pop(0)

    tarea = {
        "origen": aeropuerto_actual,
        "origen_nombre": NOMBRES_AEROPUERTOS[aeropuerto_actual],
        "destino_codigo": siguiente_ciudad["codigo"],
        "destino_nombre": siguiente_ciudad["nombre"],
        "dia_inicio": 0
    }
    
    guardar_json_storage(ARCHIVO_ESTADO, estado)
    return tarea, estado


# ======================== GENERADOR Y MOTOR DE BÚSQUEDA ======================== #
def generar_combinaciones(dia_inicio=0, dias_a_cubrir=30):
    hoy = datetime.now()
    combs = []
    for d in range(dia_inicio, min(dia_inicio + dias_a_cubrir, 32)):
        fecha_ida = hoy + timedelta(days=d)
        for dur in [1, 2, 3, 4]:
            fecha_vuelta = fecha_ida + timedelta(days=dur - 1)
            combs.append({
                "ida": fecha_ida.strftime("%Y-%m-%d"),
                "vuelta": fecha_vuelta.strftime("%Y-%m-%d"),
                "duracion": dur,
                "desplazamiento": d
            })
    return combs

def extraer_precio_chf(texto):
    m = re.search(r"(?:chf|fr\.?|\$|€)\s*(\d+[\.,]?\d*)", texto.lower())
    if not m:
        m = re.search(r"(\d+[\.,]?\d*)\s*(?:chf|fr\.?|\$|€)", texto.lower())
    if m:
        return float(m.group(1).replace(",", "."))
    cifras = re.findall(r"\b(\d{2,3})\b", texto)
    for c in cifras:
        val = float(c)
        if 20.0 <= val <= 350.0:
            return val
    return None

def simular_humano(page):
    try:
        page.mouse.move(random.randint(150, 600), random.randint(150, 400), steps=3)
        page.evaluate("window.scrollBy({ top: 120, behavior: 'smooth' });")
        time.sleep(random.uniform(0.2, 0.4))
    except Exception:
        pass

def rastrear_tarea_local(page, tarea, t_inicio):
    vuelos_nuevos = []
    origen = tarea["origen"]
    cod_dst = tarea["destino_codigo"]
    nom_dst = tarea["destino_nombre"]
    dia_inicio = tarea.get("dia_inicio", 0)

    combinaciones = generar_combinaciones(dia_inicio=dia_inicio, dias_a_cubrir=30)
    quedo_incompleta = False
    dia_corte = dia_inicio

    rutas_evaluadas = 0
    descartados_precio = 0
    descartados_escalas = 0
    precios_vistos = []

    print(f"[Rastreo] Explorando {origen} -> {nom_dst} ({cod_dst}) desde día +{dia_inicio}...")

    for c in combinaciones:
        if (time.time() - t_inicio) > TIEMPO_MAXIMO_SEGUNDOS:
            print(f"[Time-Budget] Límite de 105s alcanzado en día +{c['desplazamiento']}.")
            quedo_incompleta = True
            dia_corte = c["desplazamiento"]
            break

        rutas_evaluadas += 1
        ida = c["ida"]
        vuelta = c["vuelta"]
        dur = c["duracion"]
        tope_chf = PRESUPUESTO_ESCALONADO_CHF.get(dur, 70.0)

        url = f"https://www.google.com/travel/flights?q=Flights%20from%20{origen}%20to%20{cod_dst}%20on%20{ida}%20through%20{vuelta}&hl=es-CH&gl=ch&curr=CHF"

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=8500)
            
            try:
                b_cookie = page.locator("button:has-text('Aceptar todo'), button:has-text('Accept all')").first
                if b_cookie.is_visible(timeout=500):
                    b_cookie.click()
            except Exception:
                pass

            simular_humano(page)

            bloques = page.locator("div.pIav2d, li.pIav2d, div.yR1fYc, div[role='listitem']").all()

            for b in bloques[:4]:
                texto = b.inner_text()
                if not texto:
                    continue

                if not any(d in texto.lower() for d in ["directo", "sin escalas", "nonstop", "direkt", "sans escale"]):
                    descartados_escalas += 1
                    continue

                precio = extraer_precio_chf(texto)
                if precio:
                    precios_vistos.append(precio)
                    if precio <= tope_chf:
                        v_id = f"{origen}-{cod_dst}-{ida}-{vuelta}-{int(precio)}"
                        vuelos_nuevos.append({
                            "id": v_id,
                            "origen_iata": origen,
                            "origen_nombre": NOMBRES_AEROPUERTOS[origen],
                            "destino_codigo": cod_dst,
                            "destino_nombre": nom_dst,
                            "precio_chf": precio,
                            "presupuesto_max_chf": tope_chf,
                            "duracion_dias": dur,
                            "fechas": f"{ida} al {vuelta}",
                            "fecha_ida": ida,
                            "fecha_vuelta": vuelta,
                            "url": url,
                            "fecha_deteccion": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                        })
                    else:
                        descartados_precio += 1
        except Exception:
            continue

    metricas = {
        "rutas_evaluadas": rutas_evaluadas,
        "descartados_precio": descartados_precio,
        "descartados_escalas": descartados_escalas,
        "precio_minimo_visto": min(precios_vistos) if precios_vistos else None
    }

    return vuelos_nuevos, quedo_incompleta, dia_corte, metricas


# ======================== ENVÍO DE EMAIL ======================== #
def enviar_correo_alertas(nuevos, historial_completo, tarea):
    if not (SENDER_EMAIL and SENDER_PASSWORD and nuevos):
        return False

    origen = tarea["origen"]
    nom_ciudad = tarea["destino_nombre"]
    min_precio = min(v["precio_chf"] for v in nuevos)

    asunto = f"✈️ [{origen}] Nuevos Chollos a {nom_ciudad} ({min_precio} CHF)"

    bloques_novedades = ""
    for v in sorted(nuevos, key=lambda x: x["precio_chf"]):
        bloques_novedades += f"""
        <div style="border:1px solid #bbf7d0;background-color:#f0fdf4;border-radius:8px;padding:12px;margin-bottom:10px;">
          <table style="width:100%;border-collapse:collapse;">
            <tr>
              <td>
                <span style="background-color:#dcfce7;color:#166534;font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;">
                  {v['duracion_dias']} DÍAS · {v['fechas']}
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

    secciones_aeropuerto_html = ""
    for aero in ORDEN_AEROPUERTOS:
        lista_aero = por_aeropuerto.get(aero, [])
        if not lista_aero:
            continue

        filas = "".join([f"""
        <tr style="border-top:1px solid #f1f5f9;">
          <td style="padding:6px 0;">{item['destino_nombre']} ({item['duracion_dias']}d) - {item['fechas']}</td>
          <td style="padding:6px 0;text-align:right;font-weight:700;">{item['precio_chf']} CHF</td>
          <td style="padding:6px 0;text-align:right;width:60px;"><a href="{item['url']}" style="color:#2563eb;text-decoration:none;font-size:11px;">Reservar</a></td>
        </tr>
        """ for item in sorted(lista_aero, key=lambda x: x["precio_chf"])[:5]])

        secciones_aeropuerto_html += f"""
        <div style="background-color:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:12px;margin-bottom:12px;">
          <div style="font-weight:700;font-size:13px;color:#1e293b;margin-bottom:6px;">
            🛫 Salidas desde {NOMBRES_AEROPUERTOS.get(aero, aero)} ({len(lista_aero)} chollos guardados)
          </div>
          <table style="width:100%;font-size:12px;color:#334155;border-collapse:collapse;">
            {filas}
          </table>
        </div>
        """

    html = f"""
    <div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background-color:#f8fafc;padding:20px;color:#0f172a;">
      <div style="background-color:#0f172a;color:#fff;padding:18px;border-radius:8px 8px 0 0;text-align:center;">
        <h2 style="margin:0 0 6px 0;font-size:20px;">Radar de Vuelos Suiza</h2>
        <p style="margin:0;color:#94a3b8;font-size:13px;">Nueva alerta encontrada desde {NOMBRES_AEROPUERTOS[origen]}</p>
      </div>

      <div style="background-color:#fff;padding:20px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
        <h3 style="margin-top:0;font-size:14px;color:#16a34a;text-transform:uppercase;">🟢 Chollos Recientes Detectados</h3>
        {bloques_novedades}
      </div>

      <div style="background-color:#f1f5f9;padding:20px;border:1px solid #e2e8f0;border-radius:0 0 8px 8px;">
        <h3 style="margin-top:0;font-size:13px;color:#475569;text-transform:uppercase;">📁 Catálogo Activo por Aeropuerto de Salida</h3>
        {secciones_aeropuerto_html if secciones_aeropuerto_html else "<p style='font-size:12px;color:#64748b;'>Se actualizará a medida que avancen los aeropuertos.</p>"}
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


# ======================== SERVICIO HTTP ======================== #
app = Flask(__name__)
CORS(app)

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def buscar_vuelos_fin_de_semana_http(request=None, path=""):
    t0 = time.time()
    historial = cargar_json_storage(ARCHIVO_HISTORIAL, [])
    ids_registrados = {v.get("id") for v in historial if "id" in v}

    tarea, estado = sincronizar_cola()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            locale="es-CH",
            timezone_id="Europe/Zurich"
        )
        page = context.new_page()

        nuevos_encontrados, incompleta, corte, metricas = rastrear_tarea_local(page, tarea, t0)

        browser.close()

    # Actualizar estado del cursor
    origen_actual = tarea["origen"]
    if incompleta:
        estado["tarea_en_curso"] = {
            "origen": origen_actual,
            "origen_nombre": tarea["origen_nombre"],
            "destino_codigo": tarea["destino_codigo"],
            "destino_nombre": tarea["destino_nombre"],
            "dia_inicio": corte
        }
    else:
        estado["tarea_en_curso"] = None
        item_completado = f"{tarea['destino_nombre']} ({tarea['destino_codigo']})"
        if item_completado not in estado.get("ciudades_completadas_aeropuerto", []):
            estado.setdefault("ciudades_completadas_aeropuerto", []).append(item_completado)

    guardar_json_storage(ARCHIVO_ESTADO, estado)

    nuevos_reales = []
    for v in nuevos_encontrados:
        if v["id"] not in ids_registrados:
            nuevos_reales.append(v)
            historial.append(v)
            ids_registrados.add(v["id"])

    correo_enviado = False
    if nuevos_reales:
        correo_enviado = enviar_correo_alertas(nuevos_reales, historial, tarea)

    guardar_json_storage(ARCHIVO_HISTORIAL, historial)

    ciudades_ya_revisadas = estado.get("ciudades_completadas_aeropuerto", [])
    ciudades_pendientes_count = len(estado.get("ciudades_pendientes", []))

    return jsonify({
        "status": "ok",
        "motor": "playwright_local_chromium",
        "aeropuerto_origen": NOMBRES_AEROPUERTOS[origen_actual],
        "ciudad_procesada": f"{tarea['destino_nombre']} ({tarea['destino_codigo']})",
        "ciudades_revisadas_en_este_aeropuerto": ciudades_ya_revisadas,
        "ciudades_pendientes_en_este_aeropuerto": ciudades_pendientes_count,
        "total_rutas_fechas_evaluadas": metricas["rutas_evaluadas"],
        "descartados_por_precio_superior": metricas["descartados_precio"],
        "descartados_por_escalas": metricas["descartados_escalas"],
        "precio_minimo_visto_chf": metricas["precio_minimo_visto"],
        "nuevas_alertas": len(nuevos_reales),
        "correo_enviado": correo_enviado,
        "quedo_incompleta": incompleta,
        "duracion_segundos": round(time.time() - t0, 2),
        "total_en_catalogo": len(historial)
    }), 200

ejecutar_rastreo = buscar_vuelos_fin_de_semana_http

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=puerto)
