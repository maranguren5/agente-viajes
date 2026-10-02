import os
import re
import json
import time
import random
import smtplib
import subprocess
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

# Freno de seguridad interno: 105 segundos de rastreo neto
TIEMPO_MAXIMO_SEGUNDOS = 105.0

# Presupuesto escalonado estricto en CHF
PRESUPUESTO_ESCALONADO_CHF = {
    1: 47.5,  # 1 día
    2: 45.0,  # 2 días (1 noche)
    3: 55.0,  # 3 días (2 noches)
    4: 70.0   # 4 días (3 noches)
}

# Red completa de destinos europeos conectados de forma directa desde Suiza
# Excluida expresamente la península española (Palma de Mallorca 'PMI' permitida)
CATALOGO_DESTINOS = [
    {"codigo": "POZ", "nombre": "Poznan", "pais": "Polonia"},
    {"codigo": "ZAG", "nombre": "Zagreb", "pais": "Croacia"},
    {"codigo": "KRK", "nombre": "Cracovia", "pais": "Polonia"},
    {"codigo": "BUD", "nombre": "Budapest", "pais": "Hungría"},
    {"codigo": "PRG", "nombre": "Praga", "pais": "República Checa"},
    {"codigo": "LON", "nombre": "Londres", "pais": "Reino Unido"},
    {"codigo": "DUB", "nombre": "Dublín", "pais": "Irlanda"},
    {"codigo": "VCE", "nombre": "Venecia", "pais": "Italia"},
    {"codigo": "NCE", "nombre": "Niza", "pais": "Francia"},
    {"codigo": "PMI", "nombre": "Palma de Mallorca", "pais": "España (Baleares)"},
    {"codigo": "BER", "nombre": "Berlín", "pais": "Alemania"},
    {"codigo": "VIE", "nombre": "Viena", "pais": "Austria"},
    {"codigo": "OPO", "nombre": "Oporto", "pais": "Portugal"},
    {"codigo": "LIS", "nombre": "Lisboa", "pais": "Portugal"},
    {"codigo": "WAW", "nombre": "Varsovia", "pais": "Polonia"},
    {"codigo": "BRU", "nombre": "Bruselas", "pais": "Bélgica"},
    {"codigo": "AMS", "nombre": "Ámsterdam", "pais": "Países Bajos"},
    {"codigo": "CPH", "nombre": "Copenhague", "pais": "Dinamarca"}
]

AEROPUERTOS_SUIZA = ["BSL", "GVA", "ZRH"]


# ======================== AUTO-INSTALACIÓN NATIVA CHROMIUM ======================== #
def asegurar_instalacion_chromium():
    """Descarga Chromium de forma autónoma si falta en el contenedor."""
    ruta_cache = os.path.expanduser("~/.cache/ms-playwright")
    if not os.path.exists(ruta_cache) or not os.listdir(ruta_cache):
        print("[Playwright] Chromium no detectado en contenedor. Descargando...")
        try:
            subprocess.run(["playwright", "install", "chromium"], check=True)
            print("[Playwright] Chromium instalado con éxito.")
        except Exception as err:
            print(f"[Playwright Error] No se pudo auto-instalar: {err}")


# ======================== PERSISTENCIA EN GOOGLE CLOUD STORAGE ======================== #
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
        except Exception as e:
            print(f"[GCS Aviso] No se pudo parsear {nombre_archivo}: {e}")
    return defecto

def guardar_json_storage(nombre_archivo, datos):
    blob = obtener_blob(nombre_archivo)
    if blob:
        try:
            blob.upload_from_string(json.dumps(datos, ensure_ascii=False, indent=2), content_type="application/json")
        except Exception as e:
            print(f"[GCS Error] Fallo al escribir {nombre_archivo}: {e}")


# ======================== GESTIÓN DE COLA CIRCULAR Y CURSOR ======================== #
def obtener_siguiente_tarea():
    estado = cargar_json_storage(ARCHIVO_ESTADO, {
        "indice_catalogo": 0,
        "incompletas": []
    })

    # Prioridad: completar la ciudad que se pausó por el límite de 105s
    if estado.get("incompletas"):
        tarea = estado["incompletas"].pop(0)
        guardar_json_storage(ARCHIVO_ESTADO, estado)
        return tarea, estado

    idx = estado.get("indice_catalogo", 0) % len(CATALOGO_DESTINOS)
    destino = CATALOGO_DESTINOS[idx]
    
    estado["indice_catalogo"] = (idx + 1) % len(CATALOGO_DESTINOS)
    guardar_json_storage(ARCHIVO_ESTADO, estado)

    return {
        "codigo": destino["codigo"],
        "nombre": destino["nombre"],
        "pais": destino["pais"],
        "dia_inicio": 0
    }, estado


# ======================== COMBINACIONES DE FECHAS (1 A 4 DÍAS) ======================== #
def generar_combinaciones_mes(dia_inicio=0, total_dias=30):
    hoy = datetime.now()
    combinaciones = []
    
    for desplazamiento in range(dia_inicio, min(dia_inicio + total_dias, 32)):
        fecha_salida = hoy + timedelta(days=desplazamiento)
        for duracion in [1, 2, 3, 4]:
            fecha_regreso = fecha_salida + timedelta(days=duracion - 1)
            combinaciones.append({
                "ida": fecha_salida.strftime("%Y-%m-%d"),
                "vuelta": fecha_regreso.strftime("%Y-%m-%d"),
                "duracion": duracion,
                "desplazamiento": desplazamiento
            })
    return combinaciones


# ======================== DETECCIÓN Y EXTRACCIÓN DE PRECIO ======================== #
def extraer_precio_chf(texto):
    m = re.search(r"(?:chf|fr\.?|\$|€)\s*(\d+[\.,]?\d*)", texto.lower())
    if not m:
        m = re.search(r"(\d+[\.,]?\d*)\s*(?:chf|fr\.?|\$|€)", texto.lower())
    if m:
        return float(m.group(1).replace(",", "."))
    
    cifras = re.findall(r"\b(\d{2,3})\b", texto)
    for c in cifras:
        val = float(c)
        if 20.0 <= val <= 250.0:
            return val
    return None


# ======================== MOTOR NATIVO PLAYWRIGHT (1 GiB RAM) ======================== #
def simular_interaccion_humana(page):
    try:
        x = random.randint(180, 800)
        y = random.randint(180, 500)
        page.mouse.move(x, y, steps=4)
        page.evaluate("window.scrollBy({ top: 180, behavior: 'smooth' });")
        time.sleep(random.uniform(0.2, 0.4))
    except Exception:
        pass

def rastrear_ciudad_local(tarea):
    t_inicio = time.time()
    vuelos_encontrados = []
    
    cod_dst = tarea["codigo"]
    nom_dst = tarea["nombre"]
    dia_inicio = tarea.get("dia_inicio", 0)

    combinaciones = generar_combinaciones_mes(dia_inicio=dia_inicio, total_dias=30)
    ultimo_desplazamiento = dia_inicio
    quedo_incompleta = False

    print(f"[Chromium] Rastreando {nom_dst} ({cod_dst}) desde día +{dia_inicio}...")

    # Verificación e instalación garantizada de Chromium
    asegurar_instalacion_chromium()

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-blink-features=AutomationControlled"
                ]
            )

            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 720},
                locale="es-CH",
                timezone_id="Europe/Zurich",
                extra_http_headers={
                    "Accept-Language": "es-CH,es;q=0.9,de-CH;q=0.8,en;q=0.7"
                }
            )

            context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined });")
            page = context.new_page()

            for comb in combinaciones:
                # Freno interno de seguridad a 105s para cierre limpio
                if (time.time() - t_inicio) > TIEMPO_MAXIMO_SEGUNDOS:
                    print(f"[Time-Budget] Límite de 105s alcanzado en día +{comb['desplazamiento']}.")
                    quedo_incompleta = True
                    ultimo_desplazamiento = comb["desplazamiento"]
                    break

                origen = AEROPUERTOS_SUIZA[comb["desplazamiento"] % len(AEROPUERTOS_SUIZA)]
                ida = comb["ida"]
                vuelta = comb["vuelta"]
                dias = comb["duracion"]
                tope_chf = PRESUPUESTO_ESCALONADO_CHF.get(dias, 70.0)

                url = f"https://www.google.com/travel/flights?q=Flights%20from%20{origen}%20to%20{cod_dst}%20on%20{ida}%20through%20{vuelta}&hl=es-CH&gl=ch&curr=CHF"

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=9000)

                    # Aceptación de banner de cookies
                    try:
                        b_cookie = page.locator("button:has-text('Aceptar todo'), button:has-text('Accept all'), button:has-text('Alle akzeptieren')").first
                        if b_cookie.is_visible(timeout=600):
                            b_cookie.click()
                    except Exception:
                        pass

                    simular_interaccion_humana(page)

                    bloques = page.locator("div.pIav2d, li.pIav2d, div.yR1fYc, div[role='listitem']").all()

                    for b in bloques[:4]:
                        texto = b.inner_text()
                        if not texto:
                            continue

                        # Filtro directo multilingüe
                        if not any(d in texto.lower() for d in ["directo", "sin escalas", "nonstop", "direkt", "sans escale"]):
                            continue

                        precio = extraer_precio_chf(texto)
                        if precio and precio <= tope_chf:
                            v_id = f"{origen}-{cod_dst}-{ida}-{vuelta}-{int(precio)}"
                            if not any(v["id"] == v_id for v in vuelos_encontrados):
                                vuelos_encontrados.append({
                                    "id": v_id,
                                    "origen": f"Suiza ({origen})",
                                    "destino_codigo": cod_dst,
                                    "destino_nombre": nom_dst,
                                    "precio_chf": precio,
                                    "presupuesto_max_chf": tope_chf,
                                    "duracion_dias": dias,
                                    "fechas": f"{ida} al {vuelta}",
                                    "fecha_ida": ida,
                                    "fecha_vuelta": vuelta,
                                    "url": url,
                                    "fecha_deteccion": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
                                })
                except Exception:
                    continue

            browser.close()

        except Exception as e:
            print(f"[Chromium Error] Error en sesión Playwright: {e}")

    return vuelos_encontrados, quedo_incompleta, ultimo_desplazamiento


# ======================== ENVÍO DE EMAIL CON FORMATO DUAL ======================== #
def construir_y_enviar_email(nuevos_vuelos, historial_anterior, tarea):
    if not (SENDER_EMAIL and SENDER_PASSWORD and nuevos_vuelos):
        return False

    cod_ciudad = tarea["codigo"]
    nom_ciudad = tarea["nombre"]
    
    ciudades_previas = {v.get("destino_codigo") for v in historial_anterior}
    es_nueva_ciudad = cod_ciudad not in ciudades_previas

    vuelos_nuevos_ordenados = sorted(nuevos_vuelos, key=lambda x: x["precio_chf"])
    min_precio = vuelos_nuevos_ordenados[0]["precio_chf"]

    if es_nueva_ciudad:
        asunto = f"✈️ ¡Nueva Ciudad Descubierta: {nom_ciudad}! ({min_precio} CHF)"
        titulo_banner = f"¡Nueva Ciudad Descubierta: {nom_ciudad}!"
        subtitulo_banner = f"Entra al catálogo por primera vez con {len(vuelos_nuevos_ordenados)} opciones directas."
    else:
        asunto = f"✈️ ¡Nuevas Fechas en {nom_ciudad}! ({min_precio} CHF)"
        titulo_banner = f"¡Nuevos Chollos en {nom_ciudad}!"
        subtitulo_banner = f"Se detectaron {len(vuelos_nuevos_ordenados)} nuevas combinaciones de fechas en tu presupuesto."

    # BLOQUE 1: NOVEDADES (Verde)
    items_novedades_html = "".join([f"""
    <div style="border:1px solid #bbf7d0;background-color:#f0fdf4;border-radius:8px;padding:14px;margin-bottom:12px;">
      <table style="width:100%;border-collapse:collapse;">
        <tr>
          <td>
            <span style="background-color:#dcfce7;color:#166534;font-size:11px;font-weight:700;padding:3px 8px;border-radius:4px;">
              {v['duracion_dias']} DÍAS · {v['fechas']}
            </span>
            <div style="font-size:16px;font-weight:800;color:#0f172a;margin-top:6px;">
              🇨🇭 {v['origen']} ➔ {v['destino_nombre']} ({v['destino_codigo']})
            </div>
            <div style="font-size:12px;color:#475569;margin-top:2px;">
              Vuelo Directo · Límite aplicado: {v['presupuesto_max_chf']} CHF
            </div>
          </td>
          <td style="text-align:right;vertical-align:middle;width:115px;">
            <div style="font-size:22px;font-weight:900;color:#15803d;">{v['precio_chf']} CHF</div>
            <a href="{v['url']}" style="display:inline-block;margin-top:6px;background-color:#16a34a;color:#ffffff;text-decoration:none;font-size:11px;font-weight:700;padding:6px 12px;border-radius:4px;">Reservar</a>
          </td>
        </tr>
      </table>
    </div>
    """ for v in vuelos_nuevos_ordenados])

    # BLOQUE 2: HISTORIAL AGRUPADO POR CIUDAD (Gris / Azul)
    agrupados = defaultdict(list)
    for v in historial_anterior:
        agrupados[v.get("destino_nombre", "Otros")].append(v)

    grupos_historico_html = ""
    for ciudad_hist, lista in agrupados.items():
        filas = "".join([f"""
        <tr style="border-top:1px solid #f1f5f9;">
          <td style="padding:6px 0;">{item['duracion_dias']} Días ({item['fechas']}) · {item['origen']}</td>
          <td style="padding:6px 0;text-align:right;font-weight:700;color:#0f172a;">{item['precio_chf']} CHF</td>
          <td style="padding:6px 0;text-align:right;width:70px;">
            <a href="{item['url']}" style="color:#2563eb;text-decoration:none;font-weight:600;">Ver</a>
          </td>
        </tr>
        """ for item in sorted(lista, key=lambda x: x["precio_chf"])[:4]])

        grupos_historico_html += f"""
        <div style="background-color:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:12px 16px;margin-bottom:10px;">
          <div style="font-size:14px;font-weight:700;color:#1e293b;margin-bottom:6px;">
            🏙️ {ciudad_hist} <span style="font-size:12px;font-weight:400;color:#64748b;">— {len(lista)} opciones previas</span>
          </div>
          <table style="width:100%;font-size:12px;color:#334155;border-collapse:collapse;">
            {filas}
          </table>
        </div>
        """

    cuerpo_html = f"""
    <div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background-color:#f4f6f8;padding:20px;color:#1a202c;">
      
      <!-- ENCABEZADO -->
      <div style="background-color:#0f172a;padding:20px;border-radius:10px 10px 0 0;text-align:center;">
        <span style="background-color:#22c55e;color:#ffffff;font-size:11px;font-weight:800;padding:4px 10px;border-radius:12px;text-transform:uppercase;">Radar Suiza</span>
        <h2 style="color:#ffffff;margin:12px 0 4px 0;font-size:22px;">{titulo_banner}</h2>
        <p style="color:#94a3b8;margin:0;font-size:13px;">{subtitulo_banner}</p>
      </div>

      <!-- BLOQUE 1: NOVEDADES -->
      <div style="background-color:#ffffff;padding:20px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
        <div style="margin-bottom:14px;border-bottom:2px solid #22c55e;padding-bottom:8px;">
          <h3 style="margin:0;font-size:15px;color:#15803d;text-transform:uppercase;">🟢 Novedades Encontradas</h3>
        </div>
        {items_novedades_html}
      </div>

      <!-- BLOQUE 2: CATÁLOGO HISTÓRICO -->
      <div style="background-color:#f8fafc;padding:20px;border:1px solid #e2e8f0;border-radius:0 0 10px 10px;">
        <div style="margin-bottom:14px;border-bottom:2px solid #64748b;padding-bottom:8px;">
          <h3 style="margin:0;font-size:14px;color:#475569;text-transform:uppercase;">📁 Catálogo Activo por Ciudad</h3>
        </div>
        {grupos_historico_html if grupos_historico_html else "<p style='color:#64748b;font-size:12px;'>Primer ciclo: los vuelos se irán acumulando aquí ordenados por ciudad.</p>"}
      </div>

    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = asunto
    msg["From"] = f"Radar Vuelos Suiza <{SENDER_EMAIL}>"
    msg["To"] = RECIPIENT_EMAIL
    msg.attach(MIMEText(cuerpo_html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as s:
            s.login(SENDER_EMAIL, SENDER_PASSWORD)
            s.sendmail(SENDER_EMAIL, RECIPIENT_EMAIL, msg.as_string())
        print(f"[Email] Alerta despachada correctamente a {RECIPIENT_EMAIL}")
        return True
    except Exception as e:
        print(f"[Email Error] Error enviando correo: {e}")
        return False


# ======================== ENDPOINTS Y SERVIDOR ======================== #
app = Flask(__name__)
CORS(app)

@app.route("/api/vuelos", methods=["GET"])
def api_vuelos():
    historial = cargar_json_storage(ARCHIVO_HISTORIAL, [])
    return jsonify({"total": len(historial), "vuelos": historial}), 200

@app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
@app.route("/<path:path>", methods=["GET", "POST"])
def buscar_vuelos_fin_de_semana_http(request=None, path=""):
    t0 = time.time()
    
    # 1. Obtener siguiente ciudad de la cola circular
    tarea, estado_actual = obtener_siguiente_tarea()
    
    # 2. Cargar historial persistido en Google Cloud Storage
    historial = cargar_json_storage(ARCHIVO_HISTORIAL, [])
    ids_registrados = {v.get("id") for v in historial if "id" in v}

    # 3. Rastrear con Chromium local (freno interno a 105s)
    encontrados, incompleta, dia_corte = rastrear_ciudad_local(tarea)

    # 4. Registrar checkpoint si el ciclo se pausó por tiempo
    if incompleta:
        estado_actual["incompletas"].append({
            "codigo": tarea["codigo"],
            "nombre": tarea["nombre"],
            "pais": tarea["pais"],
            "dia_inicio": dia_corte
        })
        guardar_json_storage(ARCHIVO_ESTADO, estado_actual)

    # 5. Filtrar novedades contra el historial
    nuevos = []
    for v in encontrados:
        if v["id"] not in ids_registrados:
            nuevos.append(v)
            historial.append(v)
            ids_registrados.add(v["id"])

    # 6. Enviar correo dual si hay novedades
    correo_enviado = False
    if nuevos:
        historial_previo = [v for v in historial if v not in nuevos]
        correo_enviado = construir_y_enviar_email(nuevos, historial_previo, tarea)

    # 7. Guardar historial consolidado en Storage
    guardar_json_storage(ARCHIVO_HISTORIAL, historial)

    return jsonify({
        "status": "ok",
        "motor": "playwright_local_chromium",
        "ciudad_procesada": f"{tarea['nombre']} ({tarea['codigo']})",
        "duracion_segundos": round(time.time() - t0, 2),
        "quedo_incompleta": incompleta,
        "nuevas_alertas": len(nuevos),
        "correo_enviado": correo_enviado,
        "total_en_catalogo": len(historial)
    }), 200

ejecutar_rastreo = buscar_vuelos_fin_de_semana_http

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=puerto)
