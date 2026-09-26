try:
    import certifi
    CERT_PATH = certifi.where()
except ImportError:
    # Fallback si certifi est pas installé
    CERT_PATH = "/etc/ssl/certs/ca-certificates.crt"

import ssl
import os

os.environ['SSL_CERT_FILE'] = CERT_PATH
os.environ['REQUESTS_CA_BUNDLE'] = CERT_PATH
os.environ['CURL_CA_BUNDLE'] = CERT_PATH

ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=CERT_PATH)

print(f"✅ SSL fix chargé avec : {CERT_PATH}")
