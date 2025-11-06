# app_integrated.py
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

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Initialize database helper
db = DatabaseHelper(
    host="localhost",
    user="root",
    password="",
    database="tenders_db"
)

# Global control variables
processing_active = False
current_status = "System ready"
cycle_count = 0
console_output = []
# Aumentar límites para ver ciclos completos
MAX_CONSOLE_LINES = 1000  # De 200 a 1000 líneas
CONSOLE_DISPLAY_LINES = 200  # De 50 a 200 líneas para mostrar

# Guardar el print original
original_print = builtins.print

def capture_print(*args, **kwargs):
    """Función personalizada para capturar prints sin interferir con Flask"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    
    # Usar el print original para crear el output
    output = io.StringIO()
    original_print(*args, **kwargs, file=output)
    text = output.getvalue()
    
    # Capturar para la consola web
    if text.strip():
        lines = text.split('\n')
        for line in lines:
            if line.strip():
                console_output.append(f"[{timestamp}] {line}")
                # Mantener el buffer dentro del límite (pero más grande)
                if len(console_output) > MAX_CONSOLE_LINES:
                    console_output.pop(0)
    
    # Siempre imprimir en consola real también usando el print original
    original_print(*args, **kwargs)

# Configurar nuestro print personalizado
def setup_custom_print():
    builtins.print = capture_print

def restore_original_print():
    builtins.print = original_print

@app.route("/")
def index():
    """Render registration form with country list."""
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
    """Control panel to monitor and manage the processing."""
    users = db.get_all_users()
    users_without_cpv = db.get_users_without_cpv()
    return render_template("control.html", 
                         status=current_status,
                         processing_active=processing_active,
                         total_users=len(users),
                         users_without_cpv=len(users_without_cpv),
                         cycle_count=cycle_count,
                         console_output=console_output[-CONSOLE_DISPLAY_LINES:],  # Usar la nueva variable
                         now=datetime.datetime.now().strftime("%H:%M:%S"),
                         total_console_lines=len(console_output))

@app.route("/start-processing")
def start_processing():
    """Start the automated processing."""
    global processing_active
    processing_active = True
    add_console_message("🔄 Continuous processing STARTED")
    flash("🔄 Continuous processing started")
    return redirect(url_for("control_panel"))

@app.route("/stop-processing")
def stop_processing():
    """Stop the automated processing."""
    global processing_active
    processing_active = False
    add_console_message("⏹️ Processing STOPPED by user")
    flash("⏹️ Processing stopped")
    return redirect(url_for("control_panel"))

@app.route("/run-once")
def run_once():
    """Run one complete cycle manually."""
    thread = threading.Thread(target=run_processing_cycle)
    thread.daemon = True
    thread.start()
    add_console_message("🔃 Manual cycle execution triggered")
    flash("🔃 Running one complete cycle manually")
    return redirect(url_for("control_panel"))

@app.route("/clear-console")
def clear_console():
    """Clear the console output."""
    global console_output
    console_output = []
    add_console_message("🗑️ Console output cleared")
    flash("🗑️ Console output cleared")
    return redirect(url_for("control_panel"))

def add_console_message(message):
    """Add a message to console output."""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    console_output.append(f"[{timestamp}] {message}")
    if len(console_output) > MAX_CONSOLE_LINES:
        console_output.pop(0)

def run_processing_cycle():
    """Run one complete processing cycle."""
    global current_status, cycle_count
    
    try:
        cycle_count += 1
        print(f"\n{'='*80}")
        print(f"🔄 STARTING CYCLE #{cycle_count} - {datetime.datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*80}")
        
        # Step 1: Process users without CPVs
        current_status = f"🔍 Cycle #{cycle_count} - Extracting CPVs for new users..."
        print(current_status)
        
        # Capturar la salida de process_all_users
        print(f"📊 Checking for users without CPV associations...")
        users_processed = process_all_users()
        
        # Step 2: Fetch and match tenders
        current_status = f"📡 Cycle #{cycle_count} - Searching tenders on TED..."
        print(current_status)
        
        # Capturar la salida de fetch_tenders
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
    """Main continuous processing loop - runs without delays."""
    global current_status
    
    while True:
        if processing_active:
            run_processing_cycle()
            # Small pause between cycles
            print(f"⏳ Waiting 30 seconds before next cycle... (Next cycle: #{cycle_count + 1})")
            for i in range(30):
                if not processing_active:
                    print("⏹️ Processing stopped by user")
                    break
                time.sleep(1)
        else:
            # When stopped, check every second
            time.sleep(1)

def start_background_processing():
    """Start the background processing thread."""
    background_thread = threading.Thread(target=continuous_processing_loop)
    background_thread.daemon = True
    background_thread.start()
    print("🔄 Continuous background processing thread started")

if __name__ == "__main__":
    # Configurar nuestro print personalizado
    setup_custom_print()
    
    # Start background processing
    start_background_processing()
    
    # Start Flask app
    print("🚀 Web server started on http://localhost:5000")
    print("📊 Control panel available at http://localhost:5000/control")
    print("💡 Processing runs continuously when activated")
    print("📝 All console output from keyword_extractor and ted_fetch will be captured here")
    print("💾 Console buffer: 1000 lines max, showing last 200 lines")
    
    try:
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
    finally:
        # Restaurar el print original al salir
        restore_original_print()