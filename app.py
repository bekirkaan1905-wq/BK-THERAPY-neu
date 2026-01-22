"""
BK Therapy Rechnungsgenerator - Web App
Flask-basierte Anwendung zur Erstellung von PDF-Rechnungen
"""

import os
import io
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Flask, render_template, request, send_file, jsonify

from invoice_generator import (
    Invoice, Issuer, Client, Address, InvoiceMetadata,
    InvoiceItem, PaymentInfo, VATMode, Language,
    InvoicePDFGenerator, LayoutConfig
)

app = Flask(__name__)

# Konfiguration - Deine Firmendaten (werden vorausgefüllt)
DEFAULT_ISSUER = {
    "name": "BK THERAPY",
    "street": "Augsburgerstraße 100",
    "postal_code": "86368",
    "city": "Gersthofen",
    "phone": "+49 173 8623626",
    "email": "bk-therapy@outlook.de",
    "tax_number": "102/223/41561",
}

DEFAULT_PAYMENT = {
    "account_holder": "Bekir Kaan Gülseren",
    "iban": "DE51 7206 9736 0002 5296 37",
    "bic": "GENODEF1BLT",
    "bank_name": "",
}


@app.route("/")
def index():
    """Hauptseite mit Formular."""
    return render_template("index.html", 
                         issuer=DEFAULT_ISSUER, 
                         payment=DEFAULT_PAYMENT)


@app.route("/generate", methods=["POST"])
def generate_invoice():
    """Generiert die PDF-Rechnung aus den Formulardaten."""
    try:
        data = request.json
        
        # Aussteller
        issuer = Issuer(
            address=Address(
                name=data.get("issuer_name", ""),
                street=data.get("issuer_street", ""),
                postal_code=data.get("issuer_postal_code", ""),
                city=data.get("issuer_city", ""),
            ),
            phone=data.get("issuer_phone", ""),
            email=data.get("issuer_email", ""),
            tax_number=data.get("issuer_tax_number", ""),
        )
        
        # Kunde
        client = Client(
            address=Address(
                name=data.get("client_name", ""),
                street=data.get("client_street", ""),
                postal_code=data.get("client_postal_code", ""),
                city=data.get("client_city", ""),
            ),
        )
        
        # Rechnungsdaten
        invoice_date = None
        if data.get("invoice_date"):
            try:
                invoice_date = datetime.strptime(data["invoice_date"], "%Y-%m-%d")
            except ValueError:
                invoice_date = datetime.today()
        
        metadata = InvoiceMetadata(
            number=data.get("invoice_number", ""),
            date=invoice_date,
            service_date=invoice_date,
            title="Rechnung",
            due_days=int(data.get("due_days", 14)),
        )
        
        # Positionen
        items = []
        positions = data.get("items", [])
        for pos in positions:
            if pos.get("description") and pos.get("quantity") and pos.get("unit_price"):
                items.append(InvoiceItem(
                    description=pos["description"],
                    quantity=Decimal(str(pos["quantity"]).replace(",", ".")),
                    unit_price=Decimal(str(pos["unit_price"]).replace(",", ".")),
                    unit=pos.get("unit", ""),
                ))
        
        # Zahlungsinfo
        payment = PaymentInfo(
            account_holder=data.get("account_holder", ""),
            iban=data.get("iban", ""),
            bic=data.get("bic", ""),
            bank_name=data.get("bank_name", ""),
        )
        
        # Logo-Pfad
        logo_path = os.path.join(os.path.dirname(__file__), "static", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = None
        
        # Rechnung erstellen
        invoice = Invoice(
            issuer=issuer,
            client=client,
            metadata=metadata,
            items=items,
            payment=payment,
            vat_mode=VATMode.NONE,
            language=Language.DE,
            logo_path=logo_path,
        )
        
        # PDF generieren
        pdf_buffer = io.BytesIO()
        temp_path = f"/tmp/rechnung_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        generator = InvoicePDFGenerator(invoice)
        generator.generate(temp_path)
        
        # PDF in Buffer lesen
        with open(temp_path, "rb") as f:
            pdf_buffer.write(f.read())
        pdf_buffer.seek(0)
        
        # Temp-Datei löschen
        os.remove(temp_path)
        
        # Dateiname für Download
        filename = f"Rechnung_{data.get('invoice_number', 'neu').replace('/', '-')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        
        return send_file(
            pdf_buffer,
            mimetype="application/pdf",
            as_attachment=True,
            download_name=filename
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
