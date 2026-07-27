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

resource "google_storage_bucket_objecto" "codigo_objecto" {
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

resource "google_cloudfunctions_function" "funcion_carros" {
    name = "detectar_anomalias"
    description = "Revisa precios de carros diariamente"
    runtime = "python310"

    available_memory_mb = 256
    source_archive_bucket = google_storage_bucket.codigo_bucket.name
    source_archive_object = google_storage_bucket_objecto.codigo_objecto.name
    trigger_http = True
    entry_point = "detectar_anomalias"

    secret_enviroment_variables {
        key = "GEMINI_API_KEY"
        secret = "google_secret_manager_secret.gemini_key.secret_id"
        version = "latest"
        project_id = var.project_id
    }
    secret_enviroment_variables {
        key = "BOT_TOKEN"
        secret = "google_secret_manager_secret.bot_token.secret_id"
        version = "latest"
        project_id = var.project_id
    }
}

resource "google_cloud_scheduler_job" "programador_diario" {
    name = "job-diario-carros"
    description = " Ejecuta funcion todos los días"
    schedule = "0 9 * * *"
    time_zone = "America/Mexico_City"

    http_target {
        http_method = "GET"
        uri = google_cloudfunctions_function.funcion_carros.http_trigger_url
        oidc_token {
            service_account_email = google_cloudfunctions_function.funcion_carros.service_account_email
        }
    }
}

