import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
import json
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SITEMAP_URL = "https://www.creoven.de/sitemap/Sitemap_item.xml"
STATE_FILE = "stock_state.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def get_product_data(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        product_id = None
        status = "UNKNOWN"
        
        # Parse Schema.org JSON-LD
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                items = data.get('@graph', [data]) if isinstance(data, dict) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get('@type') == 'Product':
                        product_id = item.get('sku') or item.get('mpn') or item.get('gtin13') or item.get('gtin')
                        offers = item.get('offers', {})
                        if isinstance(offers, list):
                            offers = offers[0] if offers else {}
                        avail = offers.get('availability', '')
                        if 'InStock' in avail:
                            status = 'IN_STOCK'
                        elif 'OutOfStock' in avail:
                            status = 'OUT_OF_STOCK'
            except json.JSONDecodeError:
                continue
        
        if not product_id:
            product_id = url.rstrip('/').split('/')[-1]

        if status == "UNKNOWN":
            if '"InStock"' in r.text or "In den Warenkorb" in r.text:
                status = "IN_STOCK"
            elif '"OutOfStock"' in r.text or "Nicht auf Lager" in r.text:
                status = "OUT_OF_STOCK"

        return product_id, status
    except Exception as e:
        return None, "ERROR"

def send_email_alert(changes):
    sender = os.environ.get("SENDER_EMAIL")
    password = os.environ.get("SENDER_PASSWORD")
    receiver = os.environ.get("RECEIVER_EMAIL")

    if not sender or not password or not receiver:
        print("Missing email credentials in environment variables.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 Creoven Stock Alert: {len(changes)} Availability Changes"
    msg["From"] = sender
    msg["To"] = receiver

    html = "<h3>Creoven Ceiling Fans Availability Changes</h3>"
    html += "<table border='1' cellpadding='5' cellspacing='0'>"
    html += "<tr><th>SKU / ID</th><th>Old Status</th><th>New Status</th><th>Link</th></tr>"
    
    for c in changes:
        html += f"<tr><td><b>{c['id']}</b></td><td>{c['from']}</td><td><b>{c['to']}</b></td><td><a href='{c['url']}'>View Product</a></td></tr>"
    html += "</table>"

    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, receiver, msg.as_string())
        print("Alert email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")

def main():
    xml_res = requests.get(SITEMAP_URL, headers=HEADERS)
    root = ET.fromstring(xml_res.content)
    namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [elem.text for elem in root.findall('ns:url/ns:loc', namespace)]

    # Filter for ceiling fan URLs
    fan_urls = [u for u in urls if 'deckenventilator' in u]

    current_state = {}
    for url in fan_urls:
        product_id, status = get_product_data(url)
        if product_id:
            current_state[product_id] = {"status": status, "url": url}

    previous_state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            previous_state = json.load(f)

    changes = []
    for item_id, data in current_state.items():
        if item_id in previous_state:
            old_status = previous_state[item_id]["status"]
            new_status = data["status"]
            if old_status != new_status:
                changes.append({
                    "id": item_id,
                    "from": old_status,
                    "to": new_status,
                    "url": data["url"]
                })

    if changes:
        print(f"Detected {len(changes)} changes. Sending email...")
        send_email_alert(changes)
    else:
        print("No changes detected today.")

    with open(STATE_FILE, "w") as f:
        json.dump(current_state, f, indent=2)

if __name__ == "__main__":
    main()
