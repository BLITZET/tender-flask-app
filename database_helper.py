import mysql.connector
from mysql.connector import Error
from datetime import datetime

class DatabaseHelper:
    def __init__(self, host="localhost", user="root", password="", database="tenders_db"):
        self.host = host
        self.user = user
        self.password = password
        self.database = database

    # -------------------------------
    # 🔹 Internal helper
    # -------------------------------
    def connect(self):
        """Establece conexión con la base de datos MySQL."""
        try:
            connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database
            )
            return connection
        except Error as e:
            print(f"❌ Database connection failed: {e}")
            return None

    # -------------------------------
    # 🔹 COUNTRY METHODS
    # -------------------------------
    def get_all_countries(self):
        """Devuelve todos los países de la tabla 'paises'."""
        conn = self.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM paises ORDER BY nombre ASC")
            result = cursor.fetchall()
            return result
        except Error as e:
            print(f"❌ Error fetching countries: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def get_country_id_by_name(self, country_name):
        """Obtiene el ID del país según su nombre."""
        conn = self.connect()
        if not conn:
            return None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT id FROM paises WHERE nombre = %s", (str(country_name),))
            result = cursor.fetchone()
            if result:
                return result["id"]
            else:
                print(f"⚠️ No se encontró el país: {country_name}")
                return None
        except Error as e:
            print(f"❌ Error en get_country_id_by_name: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    # -------------------------------
    # 🔹 USER METHODS
    # -------------------------------
    def add_user(self, name, email, interests, country_id):
        """Agrega o actualiza un usuario en la base de datos."""
        conn = self.connect()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (name, email, interests, country_id)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    interests = VALUES(interests),
                    country_id = VALUES(country_id)
            """, (name, email, interests, country_id))
            conn.commit()
            print(f"✅ Usuario '{name}' guardado correctamente.")
            return True
        except Error as e:
            print(f"❌ Error adding user: {e}")
            return False
        finally:
            cursor.close()
            conn.close()


    def get_all_users(self):
        """Return all users."""
        conn = self.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users")
            return cursor.fetchall()
        finally:
            cursor.close()
            conn.close()



    # -------------------------------
    # 🔹 CPV METHODS
    # -------------------------------
    def add_cpv(self, code, description):
        """Insert a CPV code if not already exists."""
        conn = self.connect()
        if not conn:
            return None
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO cpv (cpv_code, description)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE description = VALUES(description)
            """, (code, description))
            conn.commit()
            return cursor.lastrowid or cursor.lastrowid
        except Error as e:
            print("❌ Error adding CPV:", e)
            return None
        finally:
            cursor.close()
            conn.close()

    def associate_user_cpv(self, user_id, cpv_id):
        """Link user with CPV (if not already)."""
        conn = self.connect()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT IGNORE INTO users_cpv (user_id, cpv_id)
                VALUES (%s, %s)
            """, (user_id, cpv_id))
            conn.commit()
            return True
        except Error as e:
            print("❌ Error linking user and CPV:", e)
            return False
        finally:
            cursor.close()
            conn.close()

    def get_users_without_cpv(self):
        """Fetch users who have no CPV codes associated."""
        conn = self.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT u.id, u.name, u.interests
                FROM users u
                LEFT JOIN users_cpv uc ON u.id = uc.user_id
                WHERE uc.user_id IS NULL
            """)
            return cursor.fetchall()
        except Error as e:
            print("❌ Error fetching users without CPV:", e)
            return []
        finally:
            cursor.close()
            conn.close()

    # -------------------------------
    # 🔹 SENT TENDERS METHODS
    # -------------------------------
    def tender_already_sent(self, user_id, publication_number):
        """Check if a tender was already sent to this user."""
        conn = self.connect()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM sent_tenders
                WHERE user_id = %s AND publication_number = %s
            """, (user_id, publication_number))
            return cursor.fetchone() is not None
        finally:
            cursor.close()
            conn.close()

    def record_sent_tender(self, user_id, publication_number):
        """Register a sent tender to avoid duplicates."""
        conn = self.connect()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT IGNORE INTO sent_tenders (user_id, publication_number, send_date)
                VALUES (%s, %s, %s)
            """, (user_id, publication_number, datetime.now()))
            conn.commit()
            return True
        except Error as e:
            print("❌ Error recording sent tender:", e)
            return False
        finally:
            cursor.close()
            conn.close()
    def get_countries_with_users(self):
        """Devuelve los países (de 'paises') que tienen al menos un usuario asociado."""
        conn = self.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT DISTINCT p.id, p.nombre, p.codigo_iso
                FROM paises p
                JOIN users u ON u.country_id = p.id
            """)
            return cursor.fetchall()
        except Error as e:
            print(f"❌ Error fetching countries with users: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def get_users_by_country(self, country_id):
        """Devuelve todos los usuarios asociados a un país."""
        conn = self.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT id, name, email, interests
                FROM users
                WHERE country_id = %s
            """, (country_id,))
            return cursor.fetchall()
        except Error as e:
            print(f"❌ Error fetching users by country: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def get_cpvs_for_user(self, user_id):
        """Devuelve los CPVs asociados a un usuario."""
        conn = self.connect()
        if not conn:
            return []
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT c.cpv_code AS code, c.description
                FROM cpv c
                JOIN users_cpv uc ON uc.cpv_id = c.id
                WHERE uc.user_id = %s
            """, (user_id,))
            return cursor.fetchall()
        except Exception as e:
            print(f"❌ Error fetching CPVs for user: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def was_tender_sent(self, user_id, publication_number):
        """Comprueba si ya se envió una licitación a un usuario."""
        conn = self.connect()
        if not conn:
            return False
        try:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM sent_tenders
                WHERE user_id = %s AND publication_number = %s
                LIMIT 1
            """, (user_id, publication_number))
            return cursor.fetchone() is not None
        except Error as e:
            print(f"❌ Error checking sent tender: {e}")
            return False
        finally:
            cursor.close()
            conn.close()

    def register_sent_tender(self, user_id, publication_number):
        """Registra que una licitación ha sido enviada al usuario."""
        conn = self.connect()
        if not conn:
            return
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT IGNORE INTO sent_tenders (user_id, publication_number)
                VALUES (%s, %s)
            """, (user_id, publication_number))
            conn.commit()
            print(f"🗂️ Guardado envío: user={user_id}, tender={publication_number}")
        except Error as e:
            print(f"❌ Error saving sent tender: {e}")
        finally:
            cursor.close()
            conn.close()
