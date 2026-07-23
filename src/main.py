from dotenv import load_dotenv
import pandas as pd
import requests
import os
from pydantic import BaseModel, Field
from google import genai
import gspread
import google.auth
from  datetime import date
import functions_framework


TEST = True

# 1. Definimos la estructura exacta que queremos que devuelva la API
class InformacionAuto(BaseModel):
    marca_modelo: str = Field(description="Nombre completo del auto")
    agencia: str = Field(description="Nombre de la agencia oficial en México")
    precio_de_lista: float = Field(description="Precio numérico original de lista")
    bonos_o_descuentos: str = Field(description="Detalle del bono de $X o la palabra 'Ninguno'")
    seguro_gratis: int = Field(description="1 si cuenta con un año de seguro gratis, 0 si no")
    tasa_promocional: int = Field(description="1 si tiene tasa de interés promocional, 0 si no")
    tasa_de_interes: str = Field(description="Porcentaje de la tasa o si no se sabe -1")
    precio_con_bono_o_descuento: float = Field(description="Precio final restando los bonos aplicables")
    fecha: str = Field(description="Fecha de la busqueda")

class ListaAutos(BaseModel):
    vehiculos: list[InformacionAuto]

class AutoSearcherNewSDK:
    def __init__(self, api_key: str = None):
        # Inicializa el cliente unificado de Google Gen AI
        load_dotenv()
        creds, _ = google.auth.default(scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ])
        api_key_env = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key_env:
            raise ValueError("Por favor, proporciona una clave de API (API Key) para Gemini.")
        self.client_gen = genai.Client(api_key=api_key_env)
        self.date = str(date.today())
        self.cliente_sheet = gspread.authorize(creds)
        self.id_hoja_calculo = "1apcjjnXDSFv2h2SwUXTb_8sGJVXt4ugBmryKcYeCvoY"
        self.chat_id = '5742375614'
        self.bot_token = os.getenv("BOT_TOKEN")
        if not self.bot_token:
            raise ValueError("Por favor, proporciona una clave de API (API) para el bot.")


    def search(self):
        prompt = f"""
       Search the internet for the current selling price ({self.date}) of three vehicles in Mexico, specifically for Puebla, Puebla:
        1. Geely Emgrand GF 2026
        2. BYD King 2026
        3. Kia K3 LX Automatic Transmission

        Focus on the official agency websites in Mexico at: https://www.geelymexico.com/promociones/emgrand-1 and
        https://www.kia.com/content/kwcms/mx/es/shopping-tools/promociones-new/promocion-lineup-sedan.html  and
        https://www.kia.com/mx/shopping-tools/promociones-new.html#

        Capture each list price for each agency. If you find any recurring bonus or discount, take it into account to deduct it from the original price.
        If it has one year of free insurance or a 0% opening fee, indicate it.
        If it has a promotional interest rate, indicate it; if it doesn't have one or you can't find it, put "unknown".

        Return the processed information perfectly adapting to the required JSON schema.
        """
        
        try:
            print("Iniciando búsqueda en internet con Gemini (esto puede demorar unos segundos)...")

            response = self.client_gen.interactions.create(
                model="gemini-3.1-flash-lite",
                input=prompt,
                tools=[{"type": "url_context"}],
                response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": ListaAutos.model_json_schema()},
            )
            # Cargamos el JSON de forma segura
            print('\n¡Datos extraídos con éxito!')
            recipe = ListaAutos.model_validate_json(response.output_text)
            return recipe
            
        except Exception as e:
            print(f'\nOcurrió un error inesperado: {e}')
            return None
        

    def sent_google_sheet(self, recipe):
        if not recipe or not getattr(recipe, 'vehiculos', []):
            return None
        
        hoja = self.cliente_sheet.open_by_key(self.id_hoja_calculo).sheet1
        
        # --- VALIDACIÓN DE HOJA VACÍA ---
        primera_fila = hoja.row_values(1)
        
        if not primera_fila:
            encabezados = [
                "Marca/Modelo",
                "Agencia",
                "Precio de Lista",
                "Bonos o Descuentos",
                "Seguro Gratis",
                "Tasa Promocional",
                "Tasa de Interés",
                "Precio con Bono/Descuento",
                "Fecha"
            ]
            hoja.append_row(encabezados)
            print("Hoja vacía detectada. Se han creado las columnas automáticamente.")
        # --------------------------------
        
        filas_a_insertar = []
        
        # 4. Extraemos datos, filtramos y aplicamos valores por defecto
        for auto in recipe.vehiculos:
            
            # --- CAMPOS OBLIGATORIOS ---
            # Si alguno de estos tres viene vacío, nulo o es 0, saltamos este registro
            if not auto.marca_modelo or not auto.agencia or not auto.precio_de_lista:
                print(f"Registro descartado: Falta Marca, Agencia o Precio de lista.")
                continue 
            
            # --- CAMPOS OPCIONALES ---
            # Validamos si son nulos (None) o cadenas vacías ("") para aplicar tus reglas
            
            bonos = auto.bonos_o_descuentos if auto.bonos_o_descuentos not in [None, ""] else 0
            seguro = auto.seguro_gratis if auto.seguro_gratis not in [None, ""] else 0
            tasa_promo = auto.tasa_promocional if auto.tasa_promocional not in [None, ""] else 0
            tasa_interes = auto.tasa_de_interes if auto.tasa_de_interes not in [None, ""] else -1
            
            # Si el precio con descuento viene vacío, toma el precio de lista
            precio_con_descuento = auto.precio_con_bono_o_descuento if auto.precio_con_bono_o_descuento not in [None, ""] else auto.precio_de_lista
            
            # Si la fecha viene vacía, toma self.date
            fecha = auto.fecha if auto.fecha not in [None, ""] else self.date

            # Armamos la fila ya limpia
            nueva_fila = [
                auto.marca_modelo,
                auto.agencia,
                auto.precio_de_lista,
                bonos,
                seguro,
                tasa_promo,
                tasa_interes,
                precio_con_descuento,
                fecha
            ]
            filas_a_insertar.append(nueva_fila)
            
        # 5. Insertamos los datos en la hoja de cálculo
        if filas_a_insertar:
            # Usar append_rows sube toda la lista en una sola petición (más rápido y seguro)
            hoja.append_rows(filas_a_insertar)
            print(f"¡{len(filas_a_insertar)} datos insertados correctamente!")
        else:
            print("No se insertó nada. Todos los registros fueron descartados.")


    def verificar_anomalias_google_sheet(self):
        """
        Consulta Google Sheets y evalúa los registros de la fecha actual (self.date)
        contra el histórico DE CADA MODELO INDIVIDUALMENTE usando Z-Score.
        
        Retorna:
            tuple: (hay_anomalia: bool, lista_anomalias: list[dict])
        """
        hoja = self.cliente_sheet.open_by_key(self.id_hoja_calculo).sheet1
        
        # 1. Obtener todos los registros de la Google Sheet
        registros = hoja.get_all_records()
        if not registros:
            print("La hoja de cálculo está vacía.")
            return False, []

        df = pd.DataFrame(registros)
        
        col_modelo = "Marca/Modelo"
        col_precio = "Precio con Bono/Descuento"
        col_fecha = "Fecha"
        
        if not all(col in df.columns for col in [col_modelo, col_precio, col_fecha]):
            print("Error: No se encontraron las columnas requeridas en la hoja.")
            return False, []

        df[col_precio] = pd.to_numeric(
            df[col_precio].astype(str).str.replace('$', '', regex=False).str.replace(',', '', regex=False),
            errors='coerce'
        )
        
        df[col_fecha] = df[col_fecha].astype(str).str.strip()
        fecha_actual_str = str(self.date).strip()

        # Separar histórico vs fecha actual
        df_historico = df[df[col_fecha] != fecha_actual_str].copy()
        df_hoy = df[df[col_fecha] == fecha_actual_str].copy()

        if df_hoy.empty:
            print(f"No hay registros cargados para la fecha actual: {fecha_actual_str}")
            return False, []

        if df_historico.empty:
            print("No hay registros históricos para realizar el análisis.")
            return False, []

        #  CÁLCULO ESTADÍSTICO AGRUPADO POR MODELO (Groupby)
        # Obtenemos media, desviación estándar y cantidad de registros históricos POR MODELO
        stats_por_modelo = df_historico.groupby(col_modelo)[col_precio].agg(
            media_hist='mean',
            std_hist='std',
            conteo_hist='count'
        ).reset_index()

        # Cruzar (merge) las estadísticas históricas de cada modelo con los datos de hoy
        df_hoy = df_hoy.merge(stats_por_modelo, on=col_modelo, how='inner')

        # Función para calcular el Z-Score por fila (por modelo)
        def calcular_z_score(row):
            conteo = row['conteo_hist']
            media = row['media_hist']
            std = row['std_hist']
            precio = row[col_precio]
            
            # Si es un modelo nuevo sin suficiente histórico (ej. menos de 3 registros), no lo marcamos como anómalo aún
            if pd.isna(conteo) or conteo < 3:
                return 0.0
            
            # Si todos los precios históricos del modelo fueron idénticos (desviación 0)
            if pd.isna(std) or std == 0:
                return 999.0 if precio != media else 0.0
                
            # Fórmula de Z-Score
            return abs((precio - media) / std)

        df_hoy['z_score'] = df_hoy.apply(calcular_z_score, axis=1)

        # 7. Filtrar registros que superen el umbral (2.5 desviaciones estándar para SU modelo)
        UMBRAL_DESVIACIONES = 2.5
        anomalias_df = df_hoy[df_hoy['z_score'] > UMBRAL_DESVIACIONES]

        # Convertir a lista de diccionarios para Telegram
        hay_anomalia = not anomalias_df.empty
        lista_anomalias = anomalias_df.to_dict(orient='records')

        if hay_anomalia:
            print(f"¡Atención! Se detectaron {len(lista_anomalias)} registros anómalos para {fecha_actual_str}.")
        else:
            print(f"Todos los registros de hoy están dentro de sus parámetros normales por modelo.")

        return hay_anomalia, lista_anomalias
    
    
    def enviar_alerta_telegram(self, lista_anomalias: list):
        """
        Envía una notificación estructurada a Telegram con el detalle 
        de los registros anómalos detectados.
        """
        if not lista_anomalias:
            print("No hay anomalías para notificar.")
            return

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

        # Encabezado del mensaje
        mensaje = "<b>⚠️ ALERTA DE PRECIOS ANÓMALOS</b>\n"
        mensaje += f"Se han detectado <b>{len(lista_anomalias)}</b> registro(s) fuera del rango normal:\n"
        mensaje += "─────────────────────────\n"

        # Recorremos la lista de anomalías devuelta por Pandas
        for idx, auto in enumerate(lista_anomalias, 1):
            modelo = auto.get("Marca/Modelo", "Sin modelo")
            agencia = auto.get("Agencia", "Sin agencia")
            precio = auto.get("Precio con Bono/Descuento", 0)
            fecha = auto.get("Fecha", "N/A")

            # Intentar dar formato de moneda si es numérico
            try:
                precio_formateado = f"${float(precio):,.2f}"
            except (ValueError, TypeError):
                precio_formateado = str(precio)

            mensaje += (
                f"<b>{idx}. {modelo}</b>\n"
                f"🏢 <b>Agencia:</b> {agencia}\n"
                f"💰 <b>Precio Detectado:</b> {precio_formateado}\n"
                f"📅 <b>Fecha:</b> {fecha}\n"
                "─────────────────────────\n"
            )

        mensaje += "<i>Por favor revisa la hoja de Google Sheets.</i>"

        # Parámetros para la API de Telegram
        payload = {
            "chat_id": self.chat_id,
            "text": mensaje,
            "parse_mode": "HTML"
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                print("Alerta enviada con éxito a Telegram.")
            else:
                print(f" Error al enviar a Telegram ({response.status_code}): {response.text}")
        except Exception as e:
            print(f" Excepción al conectar con la API de Telegram: {e}")


searcher = AutoSearcherNewSDK()

@functions_framework.http
def detectar_anomalias(request):

    try:
        datos = searcher.search()
        searcher.sent_google_sheet(datos)
        anomalia, lista_ano = searcher.verificar_anomalias_google_sheet()
        if anomalia:
            print('Se encontró anomalia')
            searcher.enviar_alerta_telegram(lista_ano)
            return 200
        else:
            print('No hay anomalia')
            return 200
    except Exception as e:
        print(f'Se encontró el error {e}')
        return 500

# Ejemplo de uso:
if __name__ == "__main__":
    anomalia_test, lista_ano_test = searcher.verificar_anomalias_google_sheet()
    searcher.enviar_alerta_telegram(lista_ano_test)