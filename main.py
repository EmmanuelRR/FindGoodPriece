from dotenv import load_dotenv
import os
from pydantic import BaseModel, Field
from google import genai
import gspread
import google.auth
from  datetime import date


TEST = True

# 1. Definimos la estructura exacta que queremos que devuelva la API
class InformacionAuto(BaseModel):
    marca_modelo: str = Field(description="Nombre completo del auto")
    agencia: str = Field(description="Nombre de la agencia oficial en México")
    precio_de_lista: float = Field(description="Precio numérico original de lista")
    bonos_o_descuentos: str = Field(description="Detalle del bono de $X o la palabra 'Ninguno'")
    seguro_gratis: int = Field(description="1 si cuenta con un año de seguro gratis, 0 si no")
    tasa_promocional: int = Field(description="1 si tiene tasa de interés promocional, 0 si no")
    tasa_de_interes: str = Field(description="Porcentaje de la tasa o la palabra 'desconocido'")
    precio_con_bono_o_descuento: float = Field(description="Precio final restando los bonos aplicables")
    fecha: str = Field(description="Fecha de la busqueda")


class AutoSearcherNewSDK:
    def __init__(self, api_key: str = None):
        # Inicializa el cliente unificado de Google Gen AI
        load_dotenv()
        api_key_env = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key_env:
            raise ValueError("Por favor, proporciona una clave de API (API Key) para Gemini.")
        
        self.client = genai.Client(api_key=api_key_env)
        self.date = str(date.today())

    def search(self):
        prompt = f"""
        Busca en internet el precio de venta actual ({self.date}) de tres vehículos en México, específicamente para Puebla, Puebla:
        1. Geely emgrand GF 2026
        2. BYD King 2026
        3. Kia k3 LX Transmisión Automática

        Enfócate en sitios oficiales de cada agencia en México.
        Captura cada precio de lista para cada agencia. Si encuentras algún bono o descuento recurrente, tómalo en cuenta para descontarlo al precio original. 
        Si tiene un año de seguro gratis o 0% de comisión por apertura, indícalo.
        Si cuenta con tasa de interés promocional indícala; si no tiene o no la encuentras, pon "desconocido".
        
        Devuelve la información procesada adaptándote perfectamente al esquema JSON requerido.
        """
        
        try:
            print("Iniciando búsqueda en internet con Gemini (esto puede demorar unos segundos)...")

            response = self.client.interactions.create(
                model="gemini-3.5-flash",
                input=prompt,
                #tools=[{"type": "google_search"}],
                response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": InformacionAuto.model_json_schema()},
            )
            # Cargamos el JSON de forma segura
            print('\n¡Datos extraídos con éxito!')
            recipe = InformacionAuto.model_validate_json(response.output_text)
            return recipe
            
        except Exception as e:
            print(f'\nOcurrió un error inesperado: {e}')
            return None
        

    def sent_google_sheet(self, recipe):
        # 1. Definimos los accesos de Sheets y Drive
        SCOPES = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        
        # 2. El script detecta de forma automática tu sesión de gcloud (ADC)
        creds, _ = google.auth.default(scopes=SCOPES)
        cliente = gspread.authorize(creds)

        id_hoja_calculo = "1apcjjnXDSFv2h2SwUXTb_8sGJVXt4ugBmryKcYeCvoY"
        hoja = cliente.open_by_key(id_hoja_calculo).sheet1
        
        # --- VALIDACIÓN DE HOJA VACÍA ---
        # Obtenemos los valores de la primera fila
        primera_fila = hoja.row_values(1)
        
        if not primera_fila:
            # Si no hay nada en la primera fila, creamos los encabezados
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
        
        # 4. Extraemos datos del Pydantic e insertamos la fila de datos
        auto_dict = recipe.model_dump()
        nueva_fila = [
            auto_dict.get("marca_modelo"),
            auto_dict.get("agencia"),
            auto_dict.get("precio_de_lista"),
            auto_dict.get("bonos_o_descuentos"),
            auto_dict.get("seguro_gratis"),
            auto_dict.get("tasa_promocional"),
            auto_dict.get("tasa_de_interes"),
            auto_dict.get("precio_con_bono_o_descuento"),
            auto_dict.get("fecha")
        ]
        
        hoja.append_row(nueva_fila)
        print("¡Datos insertados con éxito usando tus credenciales de gcloud!")

# Ejemplo de uso:
if __name__ == "__main__":
    searcher = AutoSearcherNewSDK()
    recipe_prueba = searcher.search()
    searcher.sent_google_sheet(recipe_prueba)