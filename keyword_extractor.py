import os
import json
from dotenv import load_dotenv
import google.generativeai as genai
from database_helper import DatabaseHelper

# Load environment variables (.env)
load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    raise ValueError("❌ GEMINI_API_KEY not found in .env")

# Configure Gemini
genai.configure(api_key=API_KEY)

# Initialize database
db = DatabaseHelper(host="localhost", user="root", password="", database="tenders_db")


def extract_cpvs_from_text(text: str):
    """
    Use Gemini to extract all relevant CPV codes and their descriptions
    from a user's interest text using the official CPV 2008 classification.
    """
    prompt = f"""
    You are an expert in European public procurement (TED.europa.eu) and the CPV (Common Procurement Vocabulary) classification system.

    TASK:
    Extract ALL relevant CPV codes from the official CPV 2008 classification that match the user's interest description.

    CRITICAL RULES:
    1. Use ONLY the official CPV 2008 codes and their exact English descriptions
    2. Focus on the most specific relevant codes (6-8 digit codes) when possible
    3. Include parent categories when they provide meaningful context
    4. Return codes that are directly related to the user's interests
    5. Maximum 10-15 most relevant CPVs - prioritize quality over quantity
    6. Must be actual CPV codes from the official classification
    7. OUTPUT CPV CODES WITHOUT DASHES (e.g., "03111000" instead of "03111000-2")

    CPV STRUCTURE EXAMPLE (with correct output format):
    - Original code: 03111000-2 → Output: "03111000": "Seeds"
    - Original code: 03111100-3 → Output: "03111100": "Soya beans"
    - Original code: 03111300-5 → Output: "03111300": "Sunflower seeds"

    USER INTEREST TEXT: "{text}"

    OUTPUT REQUIREMENTS:
    - Valid JSON format only
    - Key: CPV code WITHOUT DASHES (first 8 digits only)
    - Value: Official English description exactly as in CPV 2008
    - No explanations, no markdown, just pure JSON

    Example output format:
    {{
      "03111000": "Seeds",
      "03111100": "Soya beans", 
      "03111300": "Sunflower seeds",
      "03111400": "Cotton seeds",
      "03120000": "Horticultural and nursery products"
    }}

    Now analyze the user interest and return the relevant CPV codes:
    """

    try:
        model = genai.GenerativeModel("models/gemini-2.5-flash")
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # Clean code blocks if Gemini returns ```json ... ```
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()

        return json.loads(raw)

    except Exception as e:
        print(f"⚠️ Could not parse JSON for text '{text}': {e}")
        print("Raw output:\n", response.text if 'response' in locals() else "")
        return {}
    
def process_all_users():
    """
    Fetch all users without CPVs, extract CPV codes for each interest,
    and store them in the database.
    """
    users = db.get_users_without_cpv()
    print(f"🔍 Found {len(users)} users without CPV associations.\n")

    for u in users:
        user_id = u["id"]
        name = u["name"]
        interest_text = u["interests"]

        print(f"👤 Processing user {name} (ID {user_id})")
        print(f"   Interests: {interest_text}")

        cpv_dict = extract_cpvs_from_text(interest_text)
        if not cpv_dict:
            print("   ⚠️ No CPV codes found.\n")
            continue

        for code, description in cpv_dict.items():
            cpv_id = db.add_cpv(code, description)
            if cpv_id:
                db.associate_user_cpv(user_id, cpv_id)
                print(f"   ✅ Linked CPV {code} - {description}")
            else:
                print(f"   ⚠️ Failed to insert CPV {code}")

        print("   ✅ Finished user.\n")
    return len(users)  # Return number of processed users

if __name__ == "__main__":
    print("🚀 Starting CPV extraction process...\n")
    process_all_users()
    print("✅ All users processed.\n")
