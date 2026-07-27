terraform {
    backend "gcs" {
        bucket = "mi-proyecto-terraform-state"
        prefix = "terraform/state"
    }
}

provider "google" {
    project = var.project_id
    region = "us-central1"
}

variable "project_id" {}
variable "gemini_api_key_secret" {}
variable "bot_api_key_secret" {}

variable "client_email" {
  type        = string
  description = "Email de la Service Account que ejecuta Terraform"
}

# Comprimir el codigo
data "archive_file" "codigo_zip" {
    type = "zip"
    source_dir = "${path.module}/src"
    output_path = "${path.module}/function.zip"
    
}

resource "google_storage_bucket" "codigo_bucket" {
    name = "${var.project_id}-function-code"
    location = "US"
}

resource "google_project_service" "cloud_run_api" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

# 2. Habilitar Cloud Build API (necesaria para compilar el código Python)
resource "google_project_service" "cloud_build_api" {
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

# 3. Habilitar Artifact Registry API (donde se guardan los contenedores)
resource "google_project_service" "artifact_registry_api" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_storage_bucket_object" "codigo_objeto" {
    name = "function-${data.archive_file.codigo_zip.output_md5}.zip"
    bucket = google_storage_bucket.codigo_bucket.name
    source = data.archive_file.codigo_zip.output_path
}

# crear los secretos en secret manager

resource "google_secret_manager_secret" "gemini_key" {
    secret_id = "gemini-api-key"
    replication { 
        auto {} 
    }
}

resource "google_secret_manager_secret_version" "gemini_key_version" {
    secret = google_secret_manager_secret.gemini_key.id
    secret_data = var.gemini_api_key_secret
}

resource "google_secret_manager_secret" "bot_token" {
    secret_id = "telegram-bot-token"
    replication { 
        auto {} 
    }
}

resource "google_secret_manager_secret_version" "bot_token_version" {
    secret = google_secret_manager_secret.bot_token.id
    secret_data = var.bot_api_key_secret
}

# crear y conectar los secretos a la cloud function

resource "google_cloudfunctions2_function" "funcion_carros" {
  # Nota: Las funciones Gen 2 requieren guiones medios (-) en lugar de guiones bajos (_)
  name        = "detectar-anomalias" 
  location    = "us-central1" # Asegúrate de indicar tu región
  description = "Revisa precios de carros diariamente"

  build_config {
    runtime     = "python310"
    entry_point = "detectar_anomalias"
    source {
      storage_source {
        bucket = google_storage_bucket.codigo_bucket.name
        object = google_storage_bucket_object.codigo_objeto.name
      }
    }
  }

  service_config {
    max_instance_count    = 1
    available_memory      = "256M" # Gen 2 usa formato de cadena como "256M" o "512M"
    timeout_seconds       = 360
    service_account_email = var.client_email

    # Configuración de Secretos en Gen 2
    secret_environment_variables {
      key        = "GEMINI_API_KEY"
      project_id = var.project_id
      secret     = google_secret_manager_secret.gemini_key.secret_id
      version    = "latest"
    }

    secret_environment_variables {
      key        = "BOT_TOKEN"
      project_id = var.project_id
      secret     = google_secret_manager_secret.bot_token.secret_id
      version    = "latest"
    }
  }
}

resource "google_cloud_scheduler_job" "programador_diario" {
  name        = "job-diario-carros"
  description = "Ejecuta funcion todos los días"
  schedule    = "0 9 * * *"
  time_zone   = "America/Mexico_City"

  http_target {
    http_method = "GET"
    # En Gen 2 la URL se extrae de 'service_config[0].uri'
    uri         = google_cloudfunctions2_function.funcion_carros.service_config[0].uri

    oidc_token {
      service_account_email = var.client_email
    }
  }
}

