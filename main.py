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
from flask import Flask, jsonify, render_template_string
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

TIEMPO_MAXIMO_SEGUNDOS = 105.0

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

    if estado.get("tarea_en_curso"):
        tarea = estado["tarea_en_curso"]
        return tarea, estado

    if not estado.get("ciudades_pendientes"):
        if estado.get("ciudades_completadas_aeropuerto"):
            estado["aeropuerto_idx"] = (estado.get("aeropuerto_idx", 0) + 1) % len(ORDEN_AEROPUERTOS)
            estado["ciudades_completadas_aeropuerto"] = []

        aeropuerto_actual = ORDEN_AEROPUERTOS[estado["aeropuerto_idx"]]
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
    # Límite estricto de 30 días vista
    for d in range(dia_inicio, min(dia_inicio + dias_a_cubrir, 30)):
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

        # Si duracion es 1 dia, nos aseguramos de que Google Flights entienda ida y vuelta el mismo dia
        if dur == 1:
            url = f"https://www.google.com/travel/flights?q=Round-trip%20flights%20from%20{origen}%20to%20{cod_dst}%20departing%20{ida}%20returning%20{ida}&hl=es-CH&gl=ch&curr=CHF"
        else:
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
                            "fechas": f"{ida} al {vuelta}" if dur > 1 else f"{ida} (mismo día)",
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

# ======================== ENVÍO DE EMAIL CON ENLACE AL PORTAL ======================== #
def enviar_correo_alertas(nuevos, historial_completo, tarea, url_portal):
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

    total_guardados = len(historial_completo)

    html = f"""
    <div style="max-width:640px;margin:0 auto;font-family:-apple-system,BlinkMacSystemFont,sans-serif;background-color:#f8fafc;padding:20px;color:#0f172a;">
      <div style="background-color:#0f172a;color:#fff;padding:18px;border-radius:8px 8px 0 0;text-align:center;">
        <h2 style="margin:0 0 6px 0;font-size:20px;">Radar de Vuelos Suiza</h2>
        <p style="margin:0;color:#94a3b8;font-size:13px;">Nueva alerta encontrada desde {NOMBRES_AEROPUERTOS[origen]}</p>
      </div>

      <div style="background-color:#fff;padding:20px;border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;">
        <h3 style="margin-top:0;font-size:14px;color:#16a34a;text-transform:uppercase;">🟢 Chollos Recién Detectados</h3>
        {bloques_novedades}
      </div>

      <div style="background-color:#f1f5f9;padding:24px 20px;border:1px solid #e2e8f0;border-radius:0 0 8px 8px;text-align:center;">
        <h3 style="margin-top:0;font-size:15px;color:#1e293b;">📂 Catálogo Completo Interactivo ({total_guardados} vuelos guardados)</h3>
        <p style="font-size:13px;color:#64748b;margin-bottom:18px;">
          Entra a ver todas las carpetas organizadas por aeropuerto (Basilea, Ginebra, Zúrich) y navega por cada ciudad:
        </p>
        <a href="{url_portal}" style="display:inline-block;background-color:#2563eb;color:#ffffff;text-decoration:none;font-size:14px;font-weight:700;padding:12px 24px;border-radius:6px;box-shadow:0 2px 4px rgba(37,99,235,0.2);">
          🚀 Abrir Catálogo Completo (3 Carpetas)
        </a>
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

# ======================== VISTA WEB: PORTAL CON 3 CARPETAS ======================== #
PLANTILLA_PORTAL_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Catálogo Completo - Radar de Vuelos Suiza</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; color: #0f172a; margin: 0; padding: 20px; }
    .container { max-width: 900px; margin: 0 auto; }
    .header { background: #0f172a; color: white; padding: 24px; border-radius: 12px; margin-bottom: 24px; text-align: center; }
    .header h1 { margin: 0 0 8px 0; font-size: 26px; }
    .header p { margin: 0; color: #94a3b8; font-size: 14px; }
    
    .tabs { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
    .tab-btn { flex: 1; min-width: 200px; background: white; border: 2px solid #cbd5e1; padding: 14px; border-radius: 8px; font-size: 15px; font-weight: 700; color: #334155; cursor: pointer; text-align: center; transition: all 0.2s; }
    .tab-btn.active { background: #2563eb; color: white; border-color: #2563eb; box-shadow: 0 4px 6px -1px rgba(37,99,235,0.2); }
    
    .aeropuerto-content { display: none; }
    .aeropuerto-content.active { display: block; }
    
    .ciudad-card { background: white; border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 12px; overflow: hidden; }
    .ciudad-header { background: #f8fafc; padding: 14px 18px; font-weight: 700; font-size: 16px; cursor: pointer; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e2e8f0; }
    .ciudad-header:hover { background: #f1f5f9; }
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
      <p>Catálogo centralizado clasificado por 3 aeropuertos y por cada ciudad</p>
    </div>

    <!-- Pestañas de las 3 carpetas -->
    <div class="tabs">
      <div class="tab-btn active" onclick="cambiarAeropuerto('BSL')">📁 Basilea (BSL) ({{ resumen.BSL }} vuelos)</div>
      <div class="tab-btn" onclick="cambiarAeropuerto('GVA')">📁 Ginebra (GVA) ({{ resumen.GVA }} vuelos)</div>
      <div class="tab-btn" onclick="cambiarAeropuerto('ZRH')">📁 Zúrich (ZRH) ({{ resumen.ZRH }} vuelos)</div>
    </div>

    <!-- Contenido de cada Aeropuerto -->
    {% for aero_cod in ['BSL', 'GVA', 'ZRH'] %}
      <div id="panel-{{ aero_cod }}" class="aeropuerto-content {% if aero_cod == 'BSL' %}active{% endif %}">
        {% if vuelos_agrupados[aero_cod]|length == 0 %}
          <div class="vacio">No hay vuelos guardados todavía para este aeropuerto. El rastreador lo irá llenando automáticamente.</div>
        {% else %}
          {% for ciudad_nom, lista_vuelos in vuelos_agrupados[aero_cod].items() %}
            <div class="ciudad-card">
              <div class="ciudad-header" onclick="toggleCiudad(this)">
                <span>🏙️️ {{ ciudad_nom }}</span>
                <span class="badge">{{ lista_vuelos|length }} opciones disponibles</span>
              </div>
              <div class="vuelos-list">
                {% for v in lista_vuelos %}
                  <div class="vuelo-item">
                    <div>
                      <span class="vuelo-tag">{{ v.duracion_dias }} DÍAS · {{ v.fechas }}</span>
                      <div class="vuelo-info">🛫 {{ v.origen_nombre }} ➔ {{ v.destino_nombre }} ({{ v.destino_codigo }})</div>
                      <div style="font-size:12px;color:#64748b;">Directo · Límite presupuestario: {{ v.presupuesto_max_chf }} CHF</div>
                    </div>
                    <div style="text-align: right;">
                      <div class="vuelo-precio">{{ v.precio_chf }} CHF</div>
                      <a href="{{ v.url }}" target="_blank" class="btn-ver">Ver Vuelo</a>
                    </div>
                  </div>
                {% endfor %}
              </div>
            </div>
          {% endfor %}
        {% endif %}
      </div>
    {% endfor %}
  </div>

  <script>
    function cambiarAeropuerto(cod) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.aeropuerto-content').forEach(p => p.classList.remove('active'));
      event.target.classList.add('active');
      document.getElementById('panel-' + cod).classList.add('active');
    }

    function toggleCiudad(elem) {
      const lista = elem.nextElementSibling;
      lista.classList.toggle('open');
    }
  </script>
</body>
</html>
"""

# ======================== SERVICIO HTTP ======================== #
app = Flask(__name__)
CORS(app)

@app.route("/catalogo", methods=["GET"])
def ver_catalogo_web():
    historial = cargar_json_storage(ARCHIVO_HISTORIAL, [])
    
    # Agrupamos por Aeropuerto -> Ciudad
    agrupado = {
        "BSL": defaultdict(list),
        "GVA": defaultdict(list),
        "ZRH": defaultdict(list)
    }
    
    resumen = {"BSL": 0, "GVA": 0, "ZRH": 0}
    
    for v in historial:
        aero = v.get("origen_iata", "BSL")
        ciudad = f"{v.get('destino_nombre', 'Destino')} ({v.get('destino_codigo', '')})"
        if aero in agrupado:
            agrupado[aero][ciudad].append(v)
            resumen[aero] += 1

    # Ordenamos vuelos por precio dentro de cada ciudad
    for aero in agrupado:
        for c in agrupado[aero]:
            agrupado[aero][c].sort(key=lambda x: x.get("precio_chf", 999))

    return render_template_string(PLANTILLA_PORTAL_HTML, vuelos_agrupados=agrupado, resumen=resumen)

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
        url_portal = "https://agente-viajes-154469899823.europe-west1.run.app/catalogo"
        correo_enviado = enviar_correo_alertas(nuevos_reales, historial, tarea, url_portal)

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
        "total_en_catalogo": len(historial),
        "url_catalogo_completo": "https://agente-viajes-154469899823.europe-west1.run.app/catalogo"
    }), 200

ejecutar_rastreo = buscar_vuelos_fin_de_semana_http

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=puerto)
