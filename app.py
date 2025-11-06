# app.py
from flask import Flask, render_template, request, redirect, url_for, flash
from database_helper import DatabaseHelper
from keyword_extractor import process_all_users
from ted_fetch import main as fetch_tenders
import threading
import time
import datetime
import sys
import io
import builtins
import os

app = Flask(__name__)
app.secret_key = "supersecretkey"

# ==============================================================
#   CONFIGURACIÓN DE LA BASE DE DATOS (ajustada para producción)
# ==============================================================
db = DatabaseHelper(
    host="us22.tmd.cloud",
    user="motechno_AdriDani",
    password="Adridani1",
    database="motechno_tenders_db"
)

# ==============================================================
#               VARIABLES GLOBALES DE CONTROL
# ==============================================================
processing_active = False
current_status = "System ready"
cycle_count = 0
console_output = []
MAX_CONSOLE_LINES = 1000
CONSOLE_DISPLAY_LINES = 200

# ==============================================================
#              FUNCIONES DE CAPTURA DE CONSOLA
# ==============================================================
original_print = builtins.print

def capture_print(*args, **kwargs):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    output = io.StringIO()
    original_print(*args, **kwargs, file=output)
    text = output.getvalue()

    if text.strip():
        lines = text.split('\n')
        for line in lines:
            if line.strip():
                console_output.append(f"[{timestamp}] {line}")
                if len(console_output) > MAX_CONSOLE_LINES:
                    console_output.pop(0)
    original_print(*args, **kwargs)

def setup_custom_print():
    builtins.print = capture_print

def restore_original_print():
    builtins.print = original_print

# ==============================================================
#               FUNCIONES Y RUTAS PRINCIPALES
# ==============================================================
@app.route("/")
def index():
    countries = db.get_all_countries()
    return render_template("index.html", countries=countries, status=current_status)

@app.route("/register", methods=["POST"])
def register():
    name = request.form.get("name")
    email = request.form.get("email")
    interests = request.form.get("interests")
    country_name = request.form.get("country")

    if not name or not email or not interests or not country_name:
        flash("⚠️ All fields are required.")
        return redirect(url_for("index"))

    country_id = db.get_country_id_by_name(country_name)
    if not country_id:
        flash(f"⚠️ Country '{country_name}' is not valid.")
        return redirect(url_for("index"))

    success = db.add_user(name, email, interests, country_id)
    flash("✅ Your preferences have been saved successfully!" if success else "❌ Error saving data.")
    return redirect(url_for("index"))

@app.route("/control")
def control_panel():
    users = db.get_all_users()
    users_without_cpv = db.get_users_without_cpv()
    return render_template(
        "control.html",
        status=current_status,
        processing_active=processing_active,
        total_users=len(users),
        users_without_cpv=len(users_without_cpv),
        cycle_count=cycle_count,
        console_output=console_output[-CONSOLE_DISPLAY_LINES:],
        now=datetime.datetime.now().strftime("%H:%M:%S"),
        total_console_lines=len(console_output)
    )

@app.route("/start-processing")
def start_processing():
    global processing_active
    processing_active = True
    add_console_message("🔄 Continuous processing STARTED")
    flash("🔄 Continuous processing started")
    return redirect(url_for("control_panel"))

@app.route("/stop-processing")
def stop_processing():
    global processing_active
    processing_active = False
    add_console_message("⏹️ Processing STOPPED by user")
    flash("⏹️ Processing stopped")
    return redirect(url_for("control_panel"))

@app.route("/run-once")
def run_once():
    thread = threading.Thread(target=run_processing_cycle)
    thread.daemon = True
    thread.start()
    add_console_message("🔃 Manual cycle execution triggered")
    flash("🔃 Running one complete cycle manually")
    return redirect(url_for("control_panel"))

@app.route("/clear-console")
def clear_console():
    global console_output
    console_output = []
    add_console_message("🗑️ Console output cleared")
    flash("🗑️ Console output cleared")
    return redirect(url_for("control_panel"))

# ==============================================================
#                FUNCIONES DE PROCESAMIENTO
# ==============================================================
def add_console_message(message):
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    console_output.append(f"[{timestamp}] {message}")
    if len(console_output) > MAX_CONSOLE_LINES:
        console_output.pop(0)

def run_processing_cycle():
    global current_status, cycle_count
    try:
        cycle_count += 1
        print(f"\n{'='*80}")
        print(f"🔄 STARTING CYCLE #{cycle_count} - {datetime.datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*80}")

        current_status = f"🔍 Cycle #{cycle_count} - Extracting CPVs for new users..."
        print(current_status)
        print(f"📊 Checking for users without CPV associations...")
        users_processed = process_all_users()

        current_status = f"📡 Cycle #{cycle_count} - Searching tenders on TED..."
        print(current_status)
        fetch_tenders()

        current_status = f"✅ Cycle #{cycle_count} completed - Continuing..."
        print(current_status)
        print(f"📊 Summary: Processed {users_processed} users in this cycle")
        print(f"⏰ Cycle completed at: {datetime.datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*80}")

    except Exception as e:
        current_status = f"❌ Error in cycle #{cycle_count}: {str(e)}"
        print(current_status)
        import traceback
        print(f"🔍 Error details: {traceback.format_exc()}")

def continuous_processing_loop():
    global current_status
    while True:
        if processing_active:
            run_processing_cycle()
            print(f"⏳ Waiting 30 seconds before next cycle... (Next cycle: #{cycle_count + 1})")
            for i in range(30):
                if not processing_active:
                    print("⏹️ Processing stopped by user")
                    break
                time.sleep(1)
        else:
            time.sleep(1)

def start_background_processing():
    """Start background thread (local only)."""
    background_thread = threading.Thread(target=continuous_processing_loop)
    background_thread.daemon = True
    background_thread.start()
    print("🔄 Continuous background processing thread started")

# ==============================================================
#                  ARRANQUE AUTOMÁTICO
# ==============================================================
if __name__ == "__main__":
    setup_custom_print()
    start_background_processing()
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port, use_reloader=False)
else:
    setup_custom_print()
    # 🧠 Detectar Render para evitar hilos infinitos
    if os.getenv("RENDER") == "true":
        print("🟢 Running on Render (background processing disabled)")
    else:
        start_background_processing()
        print("🔄 Continuous background processing thread started (local mode)")

    print("🚀 Application started in production mode (prefix: /)")
