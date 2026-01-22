"""
BK Therapy - Professioneller Rechnungsgenerator
Design inspiriert von Zervant
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from datetime import datetime, timedelta
from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Optional
from enum import Enum
import os


class VATMode(Enum):
    NONE = "none"


class Language(Enum):
    DE = "de"


@dataclass
class Address:
    name: str = ""
    street: str = ""
    postal_code: str = ""
    city: str = ""


@dataclass
class Issuer:
    address: Address = field(default_factory=Address)
    phone: str = ""
    email: str = ""
    tax_number: str = ""


@dataclass
class Client:
    address: Address = field(default_factory=Address)


@dataclass
class InvoiceMetadata:
    number: str = ""
    date: datetime = None
    service_date: datetime = None
    title: str = "Rechnung"
    due_days: int = 14
    
    def __post_init__(self):
        if self.date is None:
            self.date = datetime.today()
        if self.service_date is None:
            self.service_date = self.date


@dataclass
class InvoiceItem:
    description: str = ""
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    unit: str = ""
    
    @property
    def total(self) -> Decimal:
        return self.quantity * self.unit_price


@dataclass
class PaymentInfo:
    account_holder: str = ""
    iban: str = ""
    bic: str = ""
    bank_name: str = ""


@dataclass
class LayoutConfig:
    primary_color: tuple = (0, 102, 153)


@dataclass
class Invoice:
    issuer: Issuer = field(default_factory=Issuer)
    client: Client = field(default_factory=Client)
    metadata: InvoiceMetadata = field(default_factory=InvoiceMetadata)
    items: List[InvoiceItem] = field(default_factory=list)
    payment: PaymentInfo = field(default_factory=PaymentInfo)
    vat_mode: VATMode = VATMode.NONE
    language: Language = Language.DE
    logo_path: Optional[str] = None
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    
    @property
    def subtotal(self) -> Decimal:
        return sum(item.total for item in self.items)
    
    @property
    def total(self) -> Decimal:
        return self.subtotal
    
    @property
    def due_date(self) -> datetime:
        return self.metadata.date + timedelta(days=self.metadata.due_days)


class InvoicePDFGenerator:
    def __init__(self, invoice: Invoice):
        self.invoice = invoice
        self.width, self.height = A4
        self.margin = 20 * mm
        
    def generate(self, filepath: str):
        c = canvas.Canvas(filepath, pagesize=A4)
        inv = self.invoice
        
        # ===== LOGO LINKS OBEN =====
        if inv.logo_path and os.path.exists(inv.logo_path):
            try:
                c.drawImage(inv.logo_path, self.margin, self.height - 55*mm, 
                           width=45*mm, height=45*mm, preserveAspectRatio=True, mask='auto')
            except:
                pass
        
        # ===== RECHNUNGSDETAILS RECHTS OBEN (nur 2 Zeilen) =====
        right_col = self.width - 70*mm
        y = self.height - 25*mm
        
        details = [
            ("Rechnungsnummer:", inv.metadata.number),
            ("Rechnungsdatum:", inv.metadata.date.strftime("%d.%m.%Y")),
        ]
        
        for label, value in details:
            c.setFont("Helvetica", 8)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString(right_col, y, label)
            c.setFont("Helvetica-Bold", 9)
            c.setFillColorRGB(0.2, 0.2, 0.2)
            c.drawRightString(self.width - self.margin, y, value)
            y -= 6*mm
        
        # ===== KUNDENADRESSE LINKS =====
        y = self.height - 60*mm
        
        # Zuerst Firmendaten (Absender)
        c.setFont("Helvetica-Bold", 10)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(self.margin, y, inv.issuer.address.name)
        y -= 5*mm
        c.setFont("Helvetica", 9)
        c.drawString(self.margin, y, inv.issuer.address.street)
        y -= 4*mm
        c.drawString(self.margin, y, f"{inv.issuer.address.postal_code} {inv.issuer.address.city}")
        
        y -= 12*mm
        
        # Dann Kundendaten (Empfänger)
        c.setFont("Helvetica-Bold", 11)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(self.margin, y, inv.client.address.name)
        
        c.setFont("Helvetica", 10)
        y -= 5*mm
        c.drawString(self.margin, y, inv.client.address.street)
        y -= 5*mm
        c.drawString(self.margin, y, f"{inv.client.address.postal_code} {inv.client.address.city}")
        
        # ===== TITEL "RECHNUNG" =====
        y = self.height - 105*mm
        c.setFont("Helvetica-Bold", 20)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(self.margin, y, "Rechnung")
        
        # ===== TABELLE =====
        table_top = self.height - 120*mm
        row_h = 10*mm
        
        # Spalten
        col1 = self.margin  # Beschreibung
        col2 = self.margin + 85*mm  # Menge
        col3 = self.margin + 110*mm  # Einzelpreis
        col4 = self.width - self.margin  # Betrag (rechtsbündig)
        
        # Header Hintergrund
        c.setFillColorRGB(0.95, 0.95, 0.95)
        c.rect(self.margin, table_top - row_h + 3*mm, 
               self.width - 2*self.margin, row_h, fill=True, stroke=False)
        
        # Header Text
        y = table_top - 4*mm
        c.setFont("Helvetica-Bold", 9)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.drawString(col1, y, "Leistung")
        c.drawString(col2, y, "Menge")
        c.drawString(col3, y, "Einzelpreis")
        c.drawRightString(col4, y, "Betrag")
        
        # Linie unter Header
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(1)
        c.line(self.margin, table_top - row_h + 2*mm, self.width - self.margin, table_top - row_h + 2*mm)
        
        # Items
        y = table_top - row_h - 6*mm
        c.setFont("Helvetica", 10)
        c.setFillColorRGB(0.2, 0.2, 0.2)
        
        for item in inv.items:
            c.drawString(col1, y, item.description[:45])
            c.drawString(col2, y, str(int(item.quantity)))
            c.drawString(col3, y, f"{item.unit_price:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
            c.drawRightString(col4, y, f"{item.total:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
            y -= row_h
        
        # Linie unter Items
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.line(self.margin, y + 5*mm, self.width - self.margin, y + 5*mm)
        
        # ===== SUMME =====
        y -= 5*mm
        c.setFont("Helvetica-Bold", 12)
        c.setFillColorRGB(0.1, 0.1, 0.1)
        c.drawString(col3, y, "Gesamt:")
        c.drawRightString(col4, y, f"{inv.total:,.2f} €".replace(",", "X").replace(".", ",").replace("X", "."))
        
        # ===== KLEINUNTERNEHMER HINWEIS =====
        y -= 20*mm
        c.setFont("Helvetica", 8)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(self.margin, y, "Gemäß § 19 UStG (Kleinunternehmerregelung) wird keine Umsatzsteuer ausgewiesen.")
        
        # ===== ZAHLUNGSZIEL =====
        y -= 12*mm
        c.setFont("Helvetica", 9)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.drawString(self.margin, y, f"Zahlungsziel: {inv.metadata.due_days} Tage")
        y -= 5*mm
        c.drawString(self.margin, y, f"Fällig am: {inv.due_date.strftime('%d.%m.%Y')}")
        
        # ===== FOOTER =====
        footer_y = 30*mm
        
        # Linie
        c.setStrokeColorRGB(0.85, 0.85, 0.85)
        c.setLineWidth(1)
        c.line(self.margin, footer_y + 8*mm, self.width - self.margin, footer_y + 8*mm)
        
        c.setFont("Helvetica", 7)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        
        # Links: Adresse und Kontakt
        c.drawString(self.margin, footer_y, f"Adresse: {inv.issuer.address.street}, {inv.issuer.address.postal_code} {inv.issuer.address.city}")
        c.drawString(self.margin, footer_y - 4*mm, f"Tel: {inv.issuer.phone}  •  E-Mail: {inv.issuer.email}")
        c.drawString(self.margin, footer_y - 8*mm, f"Steuernummer: {inv.issuer.tax_number}")
        
        # Rechts: Bankdaten
        if inv.payment.iban:
            c.drawRightString(self.width - self.margin, footer_y, f"Kontoinhaber: {inv.payment.account_holder}")
            c.drawRightString(self.width - self.margin, footer_y - 4*mm, f"IBAN: {inv.payment.iban}")
            c.drawRightString(self.width - self.margin, footer_y - 8*mm, f"BIC: {inv.payment.bic}")
        
        c.save()
