import requests
from bs4 import BeautifulSoup
import chardet
import json
from datetime import datetime
import os
import re
from database_helper import DatabaseHelper
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

API_URL = "https://api.ted.europa.eu/v3/notices/search"
API_KEY = "d501872dfa1c4ea4898d47f480e8ac6f"

# Configuración de email
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_USERNAME = os.getenv("EMAIL_USERNAME", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
SENDER_NAME = os.getenv("SENDER_NAME", "TED Tender Alerts")


def get_todays_notices_by_country(limit=250, country_code="ESP"):
    """Get today's tenders for a specific country"""
    payload = {
        "query": f"buyer-country={country_code} AND publication-date=today()",
        "fields": [
            "publication-number",
            "BT-05(a)-notice",
            "publication-date",
            "buyer-name",
            "buyer-country",
            "contract-nature",
            "estimated-value-lot",
            "links"
        ],
        "limit": limit
    }
    headers = {"Content-Type": "application/json", "X-API-KEY": API_KEY}
    print(f"[📡] Requesting today's tenders for country: {country_code}...")
    
    try:
        r = requests.post(API_URL, headers=headers, json=payload)
        r.raise_for_status()
        return r.json().get("notices", [])
    except Exception as e:
        print(f"[❌] Error getting tenders for {country_code}: {e}")
        return []


def detect_best_html_link(links):
    """Use English version if exists, or first available."""
    if not links:
        return None
    html_direct = links.get("htmlDirect", {})
    if not html_direct:
        return None
    if "ENG" in html_direct:
        return html_direct["ENG"]
    if len(html_direct) > 0:
        lang, url = next(iter(html_direct.items()))
        print(f"[🌍] Using alternative language: {lang}")
        return url
    return None


def clean_text(text):
    """Cleans line breaks, duplicate spaces, strange characters."""
    if not text:
        return None
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def extract_cpvs_from_div(div):
    """Extracts CPV codes and descriptions from a classification div."""
    cpvs = []
    
    # Find ALL spans with class "data" that contain CPV numbers
    data_spans = div.find_all("span", class_="data")
    
    i = 0
    while i < len(data_spans):
        span_text = clean_text(data_spans[i].get_text())
        
        # If it's a CPV code (only numbers)
        if re.match(r'^\d+$', span_text):
            cpv_code = span_text
            
            # Look for description in the next span
            if i + 1 < len(data_spans):
                next_span_text = clean_text(data_spans[i + 1].get_text())
                # If the next span is not a number, it's the description
                if not re.match(r'^\d+$', next_span_text):
                    cpv_description = next_span_text
                    cpvs.append({
                        "code": cpv_code,
                        "description": cpv_description
                    })
                    i += 2  # Skip code and description
                    continue
            
            # If no description found, only save the code
            cpvs.append({
                "code": cpv_code,
                "description": ""
            })
        
        i += 1
    
    return cpvs


def parse_html_notice(url):
    """Extracts all possible information from TED HTML in a structured way."""
    try:
        r = requests.get(url, timeout=30)
        detected = chardet.detect(r.content)
        encoding = detected.get("encoding", "utf-8") or "utf-8"
        html = r.content.decode(encoding, errors="replace")
        soup = BeautifulSoup(html, "lxml")

        result = {"url": url}

        # === MAIN HEADER ===
        header = soup.select_one(".header-content")
        if header:
            header_texts = []
            for elem in header.select(".bold"):
                text = clean_text(elem.get_text())
                if text and text not in header_texts:
                    header_texts.append(text)
            
            if header_texts:
                result["title"] = " – ".join(header_texts)

        # === PROCESS SECTIONS ===
        sections_data = {}

        # 1. BUYER SECTION
        buyer_section = soup.find("div", id="section1_1")
        if buyer_section:
            buyer_data = {}
            section_content = buyer_section.find_next_sibling("div", class_="section-content")
            if section_content:
                for div in section_content.find_all("div"):
                    label = div.find("span", class_="label")
                    if label:
                        label_text = clean_text(label.get_text())
                        value_span = div.find("span", class_="data") or div.find("span", class_="line")
                        if value_span:
                            buyer_data[label_text] = clean_text(value_span.get_text())
                        elif div.find("a"):
                            buyer_data[label_text] = div.find("a").get("href", "").strip()
            
            sections_data["1. Buyer"] = buyer_data
            result["buyer"] = {
                "official_name": buyer_data.get("Official name"),
                "email": buyer_data.get("Email"),
                "legal_type": buyer_data.get("Legal type of the buyer"),
                "activity": buyer_data.get("Activity of the contracting authority")
            }

        # 2. PROCEDURE SECTION
        procedure_section = soup.find("div", id="section2_3")
        if procedure_section:
            procedure_data = {}
            section_content = procedure_section.find_next_sibling("div", class_="section-content")
            if section_content:
                # Main procedure fields
                for div in section_content.find_all("div"):
                    label = div.find("span", class_="label")
                    if label and "subsection-content" not in div.get("class", []):
                        label_text = clean_text(label.get_text())
                        value_span = div.find("span", class_="data") or div.find("span", class_="line")
                        if value_span:
                            procedure_data[label_text] = clean_text(value_span.get_text())
                        elif div.find("a"):
                            procedure_data[label_text] = div.find("a").get("href", "").strip()

                # PROCEDURE SUBSECTIONS
                subsections = section_content.select(".subsection-content")
                for subsection in subsections:
                    # Get subsection title
                    sublevel_number = subsection.find("div", class_="sublevel__number")
                    sublevel_content = subsection.find("div", class_="sublevel__content")
                    
                    if sublevel_number and sublevel_content:
                        subsection_title = f"{clean_text(sublevel_number.get_text())} {clean_text(sublevel_content.get_text())}"
                        subsection_data = {}
                        
                        # Process subsection content
                        for div in subsection.find_all("div"):
                            label = div.find("span", class_="label")
                            if label:
                                label_text = clean_text(label.get_text())
                                
                                # For normal fields
                                value_span = div.find("span", class_="data") or div.find("span", class_="line")
                                if value_span:
                                    subsection_data[label_text] = clean_text(value_span.get_text())
                                elif div.find("a"):
                                    subsection_data[label_text] = div.find("a").get("href", "").strip()
                                
                                # Process CPV classifications
                                if "classification" in label_text.lower():
                                    cpvs = extract_cpvs_from_div(div)
                                    
                                    if "Main classification" in label_text and cpvs:
                                        main_cpv = cpvs[0]
                                        subsection_data["main_cpv_code"] = main_cpv["code"]
                                        subsection_data["main_cpv_description"] = main_cpv["description"]
                                    
                                    elif "Additional classification" in label_text and cpvs:
                                        if "additional_cpvs" not in subsection_data:
                                            subsection_data["additional_cpvs"] = []
                                        
                                        # For 2.1.1 - all additional CPVs come in a single div
                                        if subsection_title == "2.1.1. Purpose":
                                            subsection_data["additional_cpvs"].extend(cpvs)
                                        else:
                                            # For other cases, add each CPV
                                            for cpv in cpvs:
                                                subsection_data["additional_cpvs"].append(cpv)
                        
                        procedure_data[subsection_title] = subsection_data

            sections_data["2. Procedure"] = procedure_data
            
            # Extract purpose from procedure
            procedure_purpose = procedure_data.get("2.1.1. Purpose", {})
            result["procedure"] = {
                "title": procedure_data.get("Title"),
                "description": procedure_data.get("Description"),
                "internal_identifier": procedure_data.get("Internal identifier"),
                "purpose": {
                    "Main nature of the contract": procedure_purpose.get("Main nature of the contract"),
                    "main_cpv_code": procedure_purpose.get("main_cpv_code"),
                    "main_cpv_description": procedure_purpose.get("main_cpv_description"),
                    "additional_cpvs": procedure_purpose.get("additional_cpvs", [])
                }
            }

        # 3. PART SECTION  
        part_section = soup.find("div", id="section3_9")
        if part_section:
            part_data = {}
            section_content = part_section.find_next_sibling("div", class_="section-content")
            if section_content:
                # Main part fields
                for div in section_content.find_all("div"):
                    label = div.find("span", class_="label")
                    if label and "subsection-content" not in div.get("class", []):
                        label_text = clean_text(label.get_text())
                        value_span = div.find("span", class_="data") or div.find("span", class_="line")
                        if value_span:
                            part_data[label_text] = clean_text(value_span.get_text())
                        elif div.find("a"):
                            part_data[label_text] = div.find("a").get("href", "").strip()

                # PART SUBSECTIONS
                subsections = section_content.select(".subsection-content")
                for subsection in subsections:
                    # Get subsection title
                    sublevel_number = subsection.find("div", class_="sublevel__number")
                    sublevel_content = subsection.find("div", class_="sublevel__content")
                    
                    if sublevel_number and sublevel_content:
                        subsection_title = f"{clean_text(sublevel_number.get_text())} {clean_text(sublevel_content.get_text())}"
                        subsection_data = {}
                        
                        # Process subsection content
                        for div in subsection.find_all("div"):
                            label = div.find("span", class_="label")
                            if label:
                                label_text = clean_text(label.get_text())
                                
                                # For normal fields
                                value_span = div.find("span", class_="data") or div.find("span", class_="line")
                                if value_span:
                                    subsection_data[label_text] = clean_text(value_span.get_text())
                                elif div.find("a"):
                                    subsection_data[label_text] = div.find("a").get("href", "").strip()
                                
                                # Process CPV classifications
                                if "classification" in label_text.lower():
                                    cpvs = extract_cpvs_from_div(div)
                                    
                                    if "Main classification" in label_text and cpvs:
                                        main_cpv = cpvs[0]
                                        subsection_data["main_cpv_code"] = main_cpv["code"]
                                        subsection_data["main_cpv_description"] = main_cpv["description"]
                                    
                                    elif "Additional classification" in label_text and cpvs:
                                        if "additional_cpvs" not in subsection_data:
                                            subsection_data["additional_cpvs"] = []
                                        
                                        # For 3.1.1 - each CPV comes in its own div
                                        subsection_data["additional_cpvs"].extend(cpvs)
                        
                        part_data[subsection_title] = subsection_data

            sections_data["3. Part"] = part_data
            
            # Extract purpose from part
            part_purpose = part_data.get("3.1.1. Purpose", {})
            result["part"] = {
                "technical_id": part_data.get("Part technical ID"),
                "title": part_data.get("Title"),
                "description": part_data.get("Description"),
                "internal_identifier": part_data.get("Internal identifier"),
                "procurement_documents_url": part_data.get("Address of the procurement documents"),
                "purpose": {
                    "Main nature of the contract": part_purpose.get("Main nature of the contract"),
                    "main_cpv_code": part_purpose.get("main_cpv_code"),
                    "main_cpv_description": part_purpose.get("main_cpv_description"),
                    "additional_cpvs": part_purpose.get("additional_cpvs", [])
                }
            }

        result["sections"] = sections_data

        # === FULL TEXT FOR SEARCH ===
        full_plaintext = soup.get_text("\n", strip=True)
        result["raw_text_excerpt"] = full_plaintext[:4000]

        return result

    except Exception as e:
        print(f"[❌] Error processing {url}: {e}")
        import traceback
        print(f"[🔍] Error details: {traceback.format_exc()}")
        return None


def get_all_cpvs_from_tender(tender_data):
    """Extracts all CPVs from a tender"""
    cpvs = set()
    
    # Main CPV from procedure
    if tender_data.get("procedure", {}).get("purpose", {}).get("main_cpv_code"):
        cpvs.add(tender_data["procedure"]["purpose"]["main_cpv_code"])
    
    # Additional CPVs from procedure
    additional_cpvs = tender_data.get("procedure", {}).get("purpose", {}).get("additional_cpvs", [])
    for cpv in additional_cpvs:
        cpvs.add(cpv["code"])
    
    # Main CPV from part
    if tender_data.get("part", {}).get("purpose", {}).get("main_cpv_code"):
        cpvs.add(tender_data["part"]["purpose"]["main_cpv_code"])
    
    # Additional CPVs from part
    additional_cpvs_part = tender_data.get("part", {}).get("purpose", {}).get("additional_cpvs", [])
    for cpv in additional_cpvs_part:
        cpvs.add(cpv["code"])
    
    return list(cpvs)


def get_country_id_by_iso_code(db, iso_code):
    """Gets country ID based on its ISO code"""
    conn = db.connect()
    if not conn:
        return None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT id FROM paises WHERE codigo_iso = %s", (str(iso_code),))
        result = cursor.fetchone()
        if result:
            return result["id"]
        else:
            print(f"⚠️ Country not found with ISO code: {iso_code}")
            return None
    except Exception as e:
        print(f"❌ Error in get_country_id_by_iso_code: {e}")
        return None
    finally:
        cursor.close()
        conn.close()


def match_tenders_with_users(db, tenders):
    """Compares tenders with users and returns matches"""
    matches = []
    
    for tender in tenders:
        publication_number = tender.get("publication-number")
        country_codes = tender.get("buyer-country", [])
        
        if not country_codes:
            continue
            
        # For each country in the tender
        for country_code in country_codes:
            # Get users from that country using ISO code
            country_id = get_country_id_by_iso_code(db, country_code)
            if not country_id:
                continue
                
            users = db.get_users_by_country(country_id)
            
            # Get CPVs from the tender
            tender_cpvs = get_all_cpvs_from_tender(tender)
            
            for user in users:
                user_id = user["id"]
                
                # Check if this tender was already sent to the user
                if db.was_tender_sent(user_id, publication_number):
                    continue
                
                # Get user's CPVs
                user_cpvs = db.get_cpvs_for_user(user_id)
                user_cpv_codes = [cpv["code"] for cpv in user_cpvs]
                
                # Find matches
                matching_cpvs = set(tender_cpvs) & set(user_cpv_codes)
                
                if matching_cpvs:
                    matches.append({
                        "user": user,
                        "tender": tender,
                        "matching_cpvs": list(matching_cpvs),
                        "publication_number": publication_number
                    })
    
    return matches


def generate_email_content(matches):
    """Generates email content for found matches"""
    emails = {}
    
    for match in matches:
        user = match["user"]
        tender = match["tender"]
        matching_cpvs = match["matching_cpvs"]
        
        user_id = user["id"]
        if user_id not in emails:
            emails[user_id] = {
                "user": user,
                "tenders": []
            }
        
        emails[user_id]["tenders"].append({
            "tender": tender,
            "matching_cpvs": matching_cpvs
        })
    
    return emails


def get_cpv_descriptions_from_tender(tender_data, cpv_codes):
    """Gets CPV descriptions from a tender"""
    cpv_descriptions = []
    
    # Search in procedure purpose
    procedure_purpose = tender_data.get("procedure", {}).get("purpose", {})
    if procedure_purpose.get("main_cpv_code") in cpv_codes:
        cpv_descriptions.append(f"{procedure_purpose.get('main_cpv_code')} - {procedure_purpose.get('main_cpv_description', 'No description')}")
    
    additional_cpvs = procedure_purpose.get("additional_cpvs", [])
    for cpv in additional_cpvs:
        if cpv["code"] in cpv_codes:
            cpv_descriptions.append(f"{cpv['code']} - {cpv.get('description', 'No description')}")
    
    # Search in part purpose
    part_purpose = tender_data.get("part", {}).get("purpose", {})
    if part_purpose.get("main_cpv_code") in cpv_codes:
        cpv_descriptions.append(f"{part_purpose.get('main_cpv_code')} - {part_purpose.get('main_cpv_description', 'No description')}")
    
    additional_cpvs_part = part_purpose.get("additional_cpvs", [])
    for cpv in additional_cpvs_part:
        if cpv["code"] in cpv_codes:
            cpv_descriptions.append(f"{cpv['code']} - {cpv.get('description', 'No description')}")
    
    return list(set(cpv_descriptions))  # Remove duplicates


def extract_deadline_from_tender(tender_data):
    """Extracts deadline from tender"""
    # Search in sections for relevant dates
    sections = tender_data.get("sections", {})
    
    # Search in procedure
    procedure_section = sections.get("2. Procedure", {})
    for key, value in procedure_section.items():
        if "deadline" in key.lower() or "date" in key.lower():
            if isinstance(value, str) and len(value) > 5:
                return value
    
    # Search in part
    part_section = sections.get("3. Part", {})
    for key, value in part_section.items():
        if "deadline" in key.lower() or "date" in key.lower():
            if isinstance(value, str) and len(value) > 5:
                return value
    
    return "Not specified"


def get_best_html_link(tender_data):
    """Gets the best HTML link (prefers html_links over html_direct_links)"""
    html_links = tender_data.get("html_links", {})
    if "ENG" in html_links:
        return html_links["ENG"]
    elif len(html_links) > 0:
        return next(iter(html_links.values()))
    
    # Fallback to html_direct_links
    html_direct_links = tender_data.get("html_direct_links", {})
    if "ENG" in html_direct_links:
        return html_direct_links["ENG"]
    elif len(html_direct_links) > 0:
        return next(iter(html_direct_links.values()))
    
    return tender_data.get("url", "N/A")

def get_cpv_descriptions_only(tender_data, cpv_codes):
    """Gets only CPV descriptions (without codes)"""
    descriptions = set()
    
    # Search in procedure purpose
    procedure_purpose = tender_data.get("procedure", {}).get("purpose", {})
    if procedure_purpose.get("main_cpv_code") in cpv_codes:
        desc = procedure_purpose.get('main_cpv_description', '')
        if desc:
            descriptions.add(desc)
    
    additional_cpvs = procedure_purpose.get("additional_cpvs", [])
    for cpv in additional_cpvs:
        if cpv["code"] in cpv_codes:
            desc = cpv.get('description', '')
            if desc:
                descriptions.add(desc)
    
    # Search in part purpose
    part_purpose = tender_data.get("part", {}).get("purpose", {})
    if part_purpose.get("main_cpv_code") in cpv_codes:
        desc = part_purpose.get('main_cpv_description', '')
        if desc:
            descriptions.add(desc)
    
    additional_cpvs_part = part_purpose.get("additional_cpvs", [])
    for cpv in additional_cpvs_part:
        if cpv["code"] in cpv_codes:
            desc = cpv.get('description', '')
            if desc:
                descriptions.add(desc)
    
    return list(descriptions)

def send_email(to_email, to_name, subject, html_content, plain_text_content):
    """Envía un email real"""
    try:
        # Crear mensaje
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{SENDER_NAME} <{EMAIL_USERNAME}>"
        msg['To'] = to_email
        
        # Agregar ambas versiones (texto plano y HTML)
        part1 = MIMEText(plain_text_content, 'plain')
        part2 = MIMEText(html_content, 'html')
        
        msg.attach(part1)
        msg.attach(part2)
        
        # Enviar email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # Enable security
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.send_message(msg)
            
        print(f"[✅] Email enviado a {to_email}")
        return True
        
    except Exception as e:
        print(f"[❌] Error enviando email a {to_email}: {e}")
        return False

def generate_html_email_content(user, tenders_info):
    """Genera contenido HTML para el email"""
    from datetime import datetime
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .header {{ background: #f8f9fa; padding: 20px; border-radius: 5px; }}
            .tender {{ border: 1px solid #ddd; margin: 15px 0; padding: 15px; border-radius: 5px; }}
            .tender-title {{ font-size: 18px; font-weight: bold; color: #0056b3; }}
            .label {{ font-weight: bold; color: #555; }}
            .cpv-list {{ background: #f1f3f4; padding: 10px; border-radius: 3px; }}
            .footer {{ margin-top: 20px; padding: 15px; background: #f8f9fa; border-radius: 5px; font-size: 12px; color: #666; }}
            a {{ color: #0056b3; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="header">
            <h2>Hello {user['name']},</h2>
            <p>Here are the latest tenders matching your preferences.</p>
        </div>
    """
    
    for i, tender_info in enumerate(tenders_info, 1):
        tender = tender_info["tender"]
        matching_cpvs = tender_info["matching_cpvs"]
        
        cpv_descriptions = get_cpv_descriptions_from_tender(tender, matching_cpvs)
        deadline = extract_deadline_from_tender(tender)
        tender_link = get_best_html_link(tender)
        
        # Obtener la fecha actual en formato legible
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        html_content += f"""
        <div class="tender">
            <div class="tender-title">
                {i}. <a href="{tender_link}" target="_blank">{tender.get('title', 'No title available')}</a>
            </div>
            
            <p><span class="label">📋 TED Reference:</span> {tender.get('publication-number', 'N/A')}</p>
            <p><span class="label">📅 Publication date:</span> {today_date}</p>
            <p><span class="label">⏰ Deadline for submission:</span> {deadline}</p>
            <p><span class="label">💰 Estimated value:</span> {tender.get('estimated-value-lot', 'Not specified')}</p>
            <p><span class="label">🌍 Authority / Country:</span> {tender.get('buyer', {}).get('official_name', 'N/A')} / {', '.join(tender.get('buyer-country', ['N/A']))}</p>
            <p><span class="label">📝 Short description:</span> {tender.get('procedure', {}).get('description', 'No description available')}</p>
            
            <div class="label">🔗 Matching CPVs:</div>
            <div class="cpv-list">
        """
        
        for cpv_desc in cpv_descriptions:
            html_content += f"<div>• {cpv_desc}</div>"
            
        html_content += f"""
            </div>
            <p><span class="label">🌐 Link to full documentation:</span> 
               <a href="{tender_link}" target="_blank">{tender_link}</a>
            </p>
        </div>
        """
    
    html_content += f"""
        <div class="footer">
            <p>This email was sent automatically by the TED Tender Alert System.</p>
            <p>If you wish to unsubscribe or modify your preferences, please contact the system administrator.</p>
        </div>
    </body>
    </html>
    """
    
    return html_content

def generate_plain_text_email_content(user, tenders_info):
    """Genera contenido de texto plano para el email"""
    from datetime import datetime
    
    content = f"Hello {user['name']}, here are the latest tenders matching your preferences.\n\n"
    
    for i, tender_info in enumerate(tenders_info, 1):
        tender = tender_info["tender"]
        matching_cpvs = tender_info["matching_cpvs"]
        
        cpv_descriptions = get_cpv_descriptions_from_tender(tender, matching_cpvs)
        deadline = extract_deadline_from_tender(tender)
        tender_link = get_best_html_link(tender)
        
        # Obtener la fecha actual en formato legible
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        content += f"{i}. <a href='{tender_link}'>{tender.get('title', 'No title available')}</a>\n"
        content += f"   📋 TED Reference: {tender.get('publication-number', 'N/A')}\n"
        content += f"   📅 Publication date: {today_date}\n"
        content += f"   ⏰ Deadline for submission: {deadline}\n"
        content += f"   💰 Estimated value: {tender.get('estimated-value-lot', 'Not specified')}\n"
        content += f"   🌍 Authority / Country: {tender.get('buyer', {}).get('official_name', 'N/A')} / {', '.join(tender.get('buyer-country', ['N/A']))}\n"
        content += f"   📝 Short description: {tender.get('procedure', {}).get('description', 'No description available')}\n"
        content += f"   🔗 Matching CPVs:\n"
        for cpv_desc in cpv_descriptions:
            content += f"      - {cpv_desc}\n"
        content += f"   🌐 Link to full documentation: {tender_link}\n\n"
    
    content += "This email was sent automatically by the TED Tender Alert System.\n"
    
    return content

def display_email_in_console(user, tenders_info):
    """Muestra el email en la consola (comportamiento original)"""
    print("\n" + "="*80)
    print(f"📧 EMAIL FOR: {user['name']} ({user['email']})")
    print("="*80)
    
    # Generar asunto
    all_descriptions = set()
    for tender_info in tenders_info:
        tender = tender_info["tender"]
        matching_cpvs = tender_info["matching_cpvs"]
        descriptions = get_cpv_descriptions_only(tender, matching_cpvs)
        all_descriptions.update(descriptions)
    
    if all_descriptions:
        subject_keywords = list(all_descriptions)[:3]
        subject = f"{len(tenders_info)} new tenders matching your keywords: {', '.join(subject_keywords)}"
    else:
        subject = f"{len(tenders_info)} new tenders matching your interests"
    
    print(f"Subject: {subject}")
    
    # Mostrar contenido en texto plano
    plain_text_content = generate_plain_text_email_content(user, tenders_info)
    print(f"\n{plain_text_content}")
    print("-" * 80)

def process_emails(emails, send_real_emails=True):
    """Procesa y envía los emails (o los muestra en consola)"""
    sent_count = 0
    
    for user_id, email_data in emails.items():
        user = email_data["user"]
        tenders = email_data["tenders"]
        
        # Generar asunto
        all_descriptions = set()
        for tender_info in tenders:
            tender = tender_info["tender"]
            matching_cpvs = tender_info["matching_cpvs"]
            descriptions = get_cpv_descriptions_only(tender, matching_cpvs)
            all_descriptions.update(descriptions)
        
        if all_descriptions:
            subject_keywords = list(all_descriptions)[:3]
            subject = f"{len(tenders)} new tenders matching your interests"
       
        
        if send_real_emails:
            # Generar contenido para email real
            html_content = generate_html_email_content(user, tenders)
            plain_text_content = generate_plain_text_email_content(user, tenders)
            
            # Enviar email real
            success = send_email(user['email'], user['name'], subject, html_content, plain_text_content)
            if success:
                sent_count += 1
            
            # También mostrar en consola
            print(f"\n[📋] CONTENIDO DEL EMAIL ENVIADO A: {user['name']} ({user['email']})")
            print("="*60)
            print(f"Subject: {subject}")
            print(f"\n{plain_text_content}")
            print("="*60)
        else:
            # Solo mostrar en consola
            display_email_in_console(user, tenders)
    
    return sent_count

def main():
    db = DatabaseHelper()
    
    # Configurar si queremos enviar emails reales o solo mostrar
    SEND_REAL_EMAILS = True  # Cambiar a False para solo mostrar en consola
    
    if SEND_REAL_EMAILS:
        # Verificar configuración de email
        if not EMAIL_USERNAME or not EMAIL_PASSWORD:
            print("[❌] Error: Email configuration missing. Please set EMAIL_USERNAME and EMAIL_PASSWORD environment variables.")
            print("[ℹ️] Switching to console-only mode.")
            SEND_REAL_EMAILS = False
    
    # 1. Get countries with users
    countries_with_users = db.get_countries_with_users()
    print(f"[🌍] Countries with users: {[c['nombre'] for c in countries_with_users]}")
    
    all_tenders = []
    
    # 2. Get tenders for each country
    for country in countries_with_users:
        country_code = country["codigo_iso"]
        print(f"\n[🔍] Searching tenders for {country['nombre']} ({country_code})...")
        
        notices = get_todays_notices_by_country(limit=250, country_code=country_code)
        print(f"[📋] Found {len(notices)} tenders for {country_code}")
        
        # 3. Process each tender
        for notice in notices:
            links = notice.get("links", {})
            html_direct = links.get("htmlDirect", {})
            html_links = links.get("html", {})
            pdf_links = links.get("pdf", {})

            html_link = detect_best_html_link(links)
            if not html_link:
                print("[⚠] No HTML version available.")
                continue

            print(f"[🔍] Processing {html_link}")
            parsed = parse_html_notice(html_link)
            if parsed:
                # Keep original API information
                parsed["publication-number"] = notice.get("publication-number")
                parsed["buyer-country"] = notice.get("buyer-country")
                parsed["estimated-value-lot"] = notice.get("estimated-value-lot")

                # Keep all links
                parsed["html_direct_links"] = html_direct
                parsed["html_links"] = html_links
                parsed["pdf_links"] = pdf_links

                all_tenders.append(parsed)
    
    # 4. Save all tenders to JSON
    os.makedirs("output", exist_ok=True)
    filename = f"output/detailed_tenders_{datetime.now().strftime('%Y%m%d')}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(all_tenders, f, indent=4, ensure_ascii=False)
    print(f"\n[✅] Saved to {filename} ({len(all_tenders)} tenders)")
    
    # 5. Compare tenders with users
    print("\n[🔍] Comparing tenders with users...")
    matches = match_tenders_with_users(db, all_tenders)
    print(f"[✅] Found {len(matches)} matches")
    
    # 6. Generar y enviar/mostrar emails
    if matches:
        emails = generate_email_content(matches)
        print(f"\n[📧] Processing {len(emails)} emails...")
        
        sent_count = process_emails(emails, send_real_emails=SEND_REAL_EMAILS)
        
        if SEND_REAL_EMAILS:
            print(f"[✅] Successfully sent {sent_count} emails")
        else:
            print(f"[📋] Displayed {len(emails)} emails in console")
        
        # 7. Register sent tenders in database
        print("\n[💾] Registering sent tenders in database...")
        for match in matches:
            db.register_sent_tender(match["user"]["id"], match["publication_number"])
        print("[✅] Registration completed")
    else:
        print("\n[ℹ️] No matches found to send")


if __name__ == "__main__":
    main()