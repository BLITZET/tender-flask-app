# wsgi.py
import sys
import os

# Agregar el directorio actual al path
sys.path.insert(0, os.path.dirname(__file__))

# Configurar el print personalizado antes de importar la app
from app import setup_custom_print, start_background_processing, app

if __name__ == "__main__":
    setup_custom_print()
    start_background_processing()
    app.run()