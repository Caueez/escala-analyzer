"""Create an untracked deployment env file; never print credentials."""

import argparse
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser()
parser.add_argument("--development", action="store_true")
parser.add_argument("--origin", default="https://escala.example.com")
parser.add_argument("--output", type=Path, default=Path(".env"))
args = parser.parse_args()
origin = "http://localhost:8000" if args.development else args.origin
host = urlsplit(origin).hostname
if not host or (
    not args.development and (urlsplit(origin).scheme != "https" or host.endswith("example.com"))
):
    parser.error("Informe --origin https://seu-dominio; para uso local, --development.")
postgres, rabbit = secrets.token_hex(32), secrets.token_hex(32)
runtime, migrator = secrets.token_hex(32), secrets.token_hex(32)
values = {
    "POSTGRES_USER": "postgres",
    "ESCALA_DB_PASSWORD": runtime,
    "ESCALA_MIGRATOR_PASSWORD": migrator,
    "POSTGRES_PASSWORD": postgres,
    "POSTGRES_DB": "escala",
    "RABBITMQ_DEFAULT_USER": "escala",
    "RABBITMQ_DEFAULT_PASS": rabbit,
    "ESCALA_MODE": "saas",
    "ESCALA_ENVIRONMENT": "development" if args.development else "production",
    "ESCALA_DATABASE_URL": f"postgresql+psycopg://escala:{runtime}@db:5432/escala",
    "ESCALA_MIGRATION_DATABASE_URL": f"postgresql+psycopg://escala_migrator:{migrator}@db:5432/escala",
    "ESCALA_BROKER_URL": f"amqp://escala:{rabbit}@broker:5672//",
    "ESCALA_PUBLIC_ORIGIN": origin,
    "ESCALA_ALLOWED_HOSTS": json.dumps([host, "localhost", "127.0.0.1"]),
    "ESCALA_SECURE_COOKIES": "false" if args.development else "true",
    "DOMAIN": host,
}
fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as file:
    for key, value in values.items():
        file.write(f"{key}={value}\n")
print(f"Configuração criada em {args.output}. Credenciais não foram exibidas.")
