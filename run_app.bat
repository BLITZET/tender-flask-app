@echo off
echo =====================================================
echo  🚀 INICIANDO APLICACIÓN TED TENDER ALERT SYSTEM
echo =====================================================
echo.

REM Activar entorno virtual (opcional si usas venv)
IF EXIST venv\Scripts\activate (
    call venv\Scripts\activate
    echo ✅ Entorno virtual activado.
) ELSE (
    echo ⚠️ No se encontró entorno virtual. Continuando sin venv...
)

REM Instalar dependencias
echo.
echo 📦 Instalando dependencias desde requirements.txt...
pip install -r requirements.txt

REM Ejecutar la aplicación Flask
echo.
echo 🌐 Iniciando servidor Flask en http://localhost:5000 ...
python app.py

pause
