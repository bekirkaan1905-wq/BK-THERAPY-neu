import os
import io
from datetime import datetime
from decimal import Decimal
from flask import Flask, render_template, request, send_file, jsonify

from invoice_generator import (
    Invoice, Issuer, Client, Address, InvoiceMetadata,
    InvoiceItem, PaymentInfo, VATMode, Language,
    InvoicePDFGenerator
)

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/generate", methods=["POST"])
def generate_invoice():
    try:
        data = request.json
        
        issuer = Issuer(
            address=Address(
                name="BK THERAPY",
                street="Augsburgerstraße 100",
                postal_code="86368",
                city="Gersthofen",
            ),
            phone="+49 173 8623626",
            email="bk-therapy@outlook.de",
            tax_number="102/223/41561",
        )
        
        client = Client(
            address=Address(
                name=data.get("client_name", ""),
                street=data.get("client_street", ""),
                postal_code=data.get("client_postal_code", ""),
                city=data.get("client_city", ""),
            ),
        )
        
        invoice_date = datetime.today()
        if data.get("invoice_date"):
            try:
                invoice_date = datetime.strptime(data["invoice_date"], "%Y-%m-%d")
            except:
                pass
        
        metadata = InvoiceMetadata(
            number=data.get("invoice_number", ""),
            date=invoice_date,
            service_date=invoice_date,
            title="Rechnung",
            due_days=14,
        )
        
        items = []
        for pos in data.get("items", []):
            if pos.get("description") and pos.get("quantity") and pos.get("unit_price"):
                items.append(InvoiceItem(
                    description=pos["description"],
                    quantity=Decimal(str(pos["quantity"]).replace(",", ".")),
                    unit_price=Decimal(str(pos["unit_price"]).replace(",", ".")),
                    unit=pos.get("unit", ""),
                ))
        
        payment = PaymentInfo(
            account_holder="Bekir Kaan Gülseren",
            iban="DE51 7206 9736 0002 5296 37",
            bic="GENODEF1BLT",
            bank_name="",
        )
        
        logo_path = os.path.join(os.path.dirname(__file__), "static", "logo.png")
        if not os.path.exists(logo_path):
            logo_path = None
        
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
        
        pdf_buffer = io.BytesIO()
        temp_path = f"/tmp/rechnung_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        
        generator = InvoicePDFGenerator(invoice)
        generator.generate(temp_path)
        
        with open(temp_path, "rb") as f:
            pdf_buffer.write(f.read())
        pdf_buffer.seek(0)
        
        os.remove(temp_path)
        
        filename = f"Rechnung_{data.get('invoice_number', 'neu').replace('/', '-')}.pdf"
        
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
