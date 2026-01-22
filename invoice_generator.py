"""
Professioneller PDF-Rechnungsgenerator

Ein vollständig typisierter, modularer Rechnungsgenerator mit:
- Dataclasses für strukturierte Daten
- Konfigurierbarem Layout
- Optionaler Mehrwertsteuer-Berechnung
- Automatischem Seitenumbruch
- Robuster Fehlerbehandlung

Autor: Verbesserte Version
Version: 2.0.0
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


# =============================================================================
# Konstanten & Enums
# =============================================================================

class VATMode(Enum):
    """Mehrwertsteuer-Modi."""
    NONE = "none"                      # Keine MwSt (Kleinunternehmer §19 UStG)
    INCLUSIVE = "inclusive"            # MwSt inklusiv (Bruttopreise)
    EXCLUSIVE = "exclusive"            # MwSt exklusiv (Nettopreise + MwSt)


class Language(Enum):
    """Unterstützte Sprachen."""
    DE = "de"
    EN = "en"


# =============================================================================
# Übersetzungen
# =============================================================================

TRANSLATIONS: dict[Language, dict[str, str]] = {
    Language.DE: {
        "invoice": "Rechnung",
        "invoice_number": "Rechnungsnummer",
        "invoice_date": "Rechnungsdatum",
        "service_date": "Leistungsdatum",
        "bill_to": "Rechnung an:",
        "service": "Leistung",
        "quantity": "Menge",
        "unit_price": "Einzelpreis",
        "amount": "Betrag",
        "subtotal": "Zwischensumme",
        "vat": "MwSt.",
        "total": "Gesamt",
        "payment_terms": "Zahlungsziel",
        "due_date": "Fällig am",
        "days": "Tage",
        "account_holder": "Kontoinhaber",
        "vat_note_small_business": "Gemäß § 19 UStG (Kleinunternehmerregelung) wird keine Umsatzsteuer ausgewiesen.",
        "vat_id": "USt-IdNr.",
        "tax_number": "St-Nr.",
        "phone": "Tel",
        "page": "Seite",
    },
    Language.EN: {
        "invoice": "Invoice",
        "invoice_number": "Invoice Number",
        "invoice_date": "Invoice Date",
        "service_date": "Service Date",
        "bill_to": "Bill to:",
        "service": "Description",
        "quantity": "Qty",
        "unit_price": "Unit Price",
        "amount": "Amount",
        "subtotal": "Subtotal",
        "vat": "VAT",
        "total": "Total",
        "payment_terms": "Payment Terms",
        "due_date": "Due Date",
        "days": "days",
        "account_holder": "Account Holder",
        "vat_note_small_business": "No VAT charged according to § 19 UStG (small business regulation).",
        "vat_id": "VAT ID",
        "tax_number": "Tax No.",
        "phone": "Phone",
        "page": "Page",
    },
}


# =============================================================================
# Konfiguration
# =============================================================================

@dataclass(frozen=True)
class LayoutConfig:
    """Konfiguration für das PDF-Layout."""
    
    # Seitenränder
    margin_x: float = 20 * mm
    margin_top: float = 15 * mm
    margin_bottom: float = 20 * mm
    
    # Logo
    logo_width: float = 70 * mm
    logo_height: float = 50 * mm
    
    # Schriftgrößen
    font_size_title: int = 16
    font_size_header: int = 11
    font_size_normal: int = 9
    font_size_small: int = 8
    
    # Abstände
    line_height: float = 4 * mm
    section_gap: float = 8 * mm
    table_row_height: float = 5 * mm
    
    # Tabelle
    description_wrap_width: int = 55
    
    # Zahlungsziel
    default_due_days: int = 14
    
    # Seitenumbruch-Schwelle
    page_break_threshold: float = 40 * mm


@dataclass(frozen=True)
class StyleConfig:
    """Konfiguration für Farben und Stile."""
    
    primary_color: colors.Color = colors.HexColor("#2C3E50")
    secondary_color: colors.Color = colors.HexColor("#7F8C8D")
    line_color: colors.Color = colors.black
    
    header_line_width: float = 1.0
    table_line_width: float = 0.5
    
    font_regular: str = "Helvetica"
    font_bold: str = "Helvetica-Bold"


# =============================================================================
# Datenmodelle
# =============================================================================

@dataclass
class Address:
    """Adressdaten."""
    name: str
    street: str = ""
    postal_code: str = ""
    city: str = ""
    country: str = ""
    additional_lines: list[str] = field(default_factory=list)
    
    def to_lines(self) -> list[str]:
        """Konvertiert die Adresse in Zeilen für die Anzeige."""
        lines = []
        if self.street:
            lines.append(self.street)
        if self.postal_code or self.city:
            lines.append(f"{self.postal_code} {self.city}".strip())
        if self.country:
            lines.append(self.country)
        lines.extend(self.additional_lines)
        return lines


@dataclass
class Issuer:
    """Rechnungsaussteller."""
    address: Address
    phone: str = ""
    email: str = ""
    tax_number: str = ""
    vat_id: str = ""
    website: str = ""
    
    def validate(self) -> list[str]:
        """Validiert die Ausstellerdaten und gibt Warnungen zurück."""
        warnings = []
        if not self.address.name:
            warnings.append("Aussteller: Name fehlt")
        return warnings


@dataclass
class Client:
    """Rechnungsempfänger."""
    address: Address
    client_number: str = ""
    vat_id: str = ""
    
    def validate(self) -> list[str]:
        """Validiert die Kundendaten und gibt Warnungen zurück."""
        warnings = []
        if not self.address.name:
            warnings.append("Kunde: Name fehlt")
        return warnings


@dataclass
class InvoiceItem:
    """Einzelne Rechnungsposition."""
    description: str
    quantity: Decimal
    unit_price: Decimal
    unit: str = ""
    vat_rate: Decimal = Decimal("0")
    
    @property
    def net_amount(self) -> Decimal:
        """Berechnet den Nettobetrag."""
        return (self.quantity * self.unit_price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    
    @property
    def vat_amount(self) -> Decimal:
        """Berechnet den MwSt-Betrag."""
        return (self.net_amount * self.vat_rate / 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    
    @property
    def gross_amount(self) -> Decimal:
        """Berechnet den Bruttobetrag."""
        return self.net_amount + self.vat_amount
    
    @classmethod
    def from_dict(cls, data: dict) -> InvoiceItem:
        """Erstellt ein InvoiceItem aus einem Dictionary."""
        return cls(
            description=str(data.get("description", "")),
            quantity=_to_decimal(data.get("qty", data.get("quantity", 1))),
            unit_price=_to_decimal(data.get("unit_price", 0)),
            unit=str(data.get("unit", "")),
            vat_rate=_to_decimal(data.get("vat_rate", 0)),
        )
    
    def validate(self) -> list[str]:
        """Validiert die Position und gibt Warnungen zurück."""
        warnings = []
        if not self.description.strip():
            warnings.append("Position: Beschreibung fehlt")
        if self.quantity <= 0:
            warnings.append(f"Position '{self.description}': Menge muss positiv sein")
        if self.unit_price < 0:
            warnings.append(f"Position '{self.description}': Preis darf nicht negativ sein")
        return warnings


@dataclass
class PaymentInfo:
    """Zahlungsinformationen."""
    account_holder: str = ""
    iban: str = ""
    bic: str = ""
    bank_name: str = ""
    payment_reference: str = ""
    
    def validate(self) -> list[str]:
        """Validiert die Zahlungsinformationen und gibt Warnungen zurück."""
        warnings = []
        if not self.iban:
            warnings.append("Zahlung: IBAN fehlt")
        return warnings


@dataclass
class InvoiceMetadata:
    """Rechnungsmetadaten."""
    number: str
    date: Optional[datetime] = None
    service_date: Optional[datetime] = None
    service_period_start: Optional[datetime] = None
    service_period_end: Optional[datetime] = None
    title: str = ""
    due_days: int = 14
    notes: list[str] = field(default_factory=list)
    
    def __post_init__(self):
        if self.date is None:
            self.date = datetime.today()
        if self.service_date is None:
            self.service_date = self.date
    
    @property
    def due_date(self) -> datetime:
        """Berechnet das Fälligkeitsdatum."""
        return self.date + timedelta(days=self.due_days)
    
    def validate(self) -> list[str]:
        """Validiert die Metadaten und gibt Warnungen zurück."""
        warnings = []
        if not self.number:
            warnings.append("Rechnung: Nummer fehlt")
        return warnings


@dataclass
class Invoice:
    """Vollständige Rechnung."""
    issuer: Issuer
    client: Client
    metadata: InvoiceMetadata
    items: list[InvoiceItem]
    payment: PaymentInfo
    vat_mode: VATMode = VATMode.NONE
    language: Language = Language.DE
    logo_path: Optional[str] = None
    
    @property
    def subtotal(self) -> Decimal:
        """Berechnet die Zwischensumme (Netto)."""
        return sum((item.net_amount for item in self.items), Decimal("0"))
    
    @property
    def total_vat(self) -> Decimal:
        """Berechnet die gesamte MwSt."""
        return sum((item.vat_amount for item in self.items), Decimal("0"))
    
    @property
    def total(self) -> Decimal:
        """Berechnet den Gesamtbetrag."""
        if self.vat_mode == VATMode.NONE:
            return self.subtotal
        return self.subtotal + self.total_vat
    
    @property
    def vat_summary(self) -> dict[Decimal, Decimal]:
        """Gruppiert MwSt-Beträge nach Steuersatz."""
        summary: dict[Decimal, Decimal] = {}
        for item in self.items:
            if item.vat_rate > 0:
                if item.vat_rate not in summary:
                    summary[item.vat_rate] = Decimal("0")
                summary[item.vat_rate] += item.vat_amount
        return summary
    
    def validate(self) -> list[str]:
        """Validiert die gesamte Rechnung und gibt Warnungen zurück."""
        warnings = []
        warnings.extend(self.issuer.validate())
        warnings.extend(self.client.validate())
        warnings.extend(self.metadata.validate())
        warnings.extend(self.payment.validate())
        for item in self.items:
            warnings.extend(item.validate())
        if not self.items:
            warnings.append("Rechnung: Keine Positionen vorhanden")
        return warnings
    
    def t(self, key: str) -> str:
        """Übersetzt einen Schlüssel in die Rechnungssprache."""
        return TRANSLATIONS.get(self.language, TRANSLATIONS[Language.DE]).get(key, key)


# =============================================================================
# Hilfsfunktionen
# =============================================================================

def _to_decimal(value, default: Decimal = Decimal("0")) -> Decimal:
    """Konvertiert einen Wert sicher in Decimal."""
    if isinstance(value, Decimal):
        return value
    try:
        cleaned = str(value).replace(",", ".").strip()
        return Decimal(cleaned)
    except Exception:
        return default


def format_currency(
    amount: Decimal | float,
    currency: str = "€",
    locale: Language = Language.DE
) -> str:
    """
    Formatiert einen Betrag als Währungsstring.
    
    Args:
        amount: Der zu formatierende Betrag
        currency: Währungssymbol
        locale: Spracheinstellung für die Formatierung
    
    Returns:
        Formatierter Währungsstring
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    
    # Auf 2 Dezimalstellen runden
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    
    if locale == Language.DE:
        # Deutsche Formatierung: 1.234,56 €
        sign = "-" if amount < 0 else ""
        amount = abs(amount)
        int_part = int(amount)
        dec_part = int((amount % 1) * 100)
        
        # Tausendertrennzeichen
        int_str = f"{int_part:,}".replace(",", ".")
        
        return f"{sign}{int_str},{dec_part:02d} {currency}"
    else:
        # Englische Formatierung: €1,234.56
        return f"{currency}{amount:,.2f}"


def format_date(date: datetime, locale: Language = Language.DE) -> str:
    """
    Formatiert ein Datum entsprechend der Spracheinstellung.
    
    Args:
        date: Das zu formatierende Datum
        locale: Spracheinstellung
    
    Returns:
        Formatierter Datumsstring
    """
    if locale == Language.DE:
        return date.strftime("%d.%m.%Y")
    return date.strftime("%Y-%m-%d")


def format_quantity(qty: Decimal, unit: str = "") -> str:
    """
    Formatiert eine Menge mit optionaler Einheit.
    
    Args:
        qty: Die Menge
        unit: Optionale Einheit
    
    Returns:
        Formatierter Mengenstring
    """
    # Ganze Zahlen ohne Dezimalstellen anzeigen
    if qty == qty.to_integral_value():
        qty_str = str(int(qty))
    else:
        qty_str = str(qty.normalize())
    
    if unit:
        return f"{qty_str} {unit}"
    return qty_str


# =============================================================================
# PDF-Generator
# =============================================================================

class InvoicePDFGenerator:
    """
    Generiert professionelle PDF-Rechnungen.
    
    Beispiel:
        ```python
        invoice = Invoice(...)
        generator = InvoicePDFGenerator(invoice)
        generator.generate("rechnung.pdf")
        ```
    """
    
    def __init__(
        self,
        invoice: Invoice,
        layout: Optional[LayoutConfig] = None,
        style: Optional[StyleConfig] = None,
    ):
        """
        Initialisiert den PDF-Generator.
        
        Args:
            invoice: Die zu generierende Rechnung
            layout: Optionale Layout-Konfiguration
            style: Optionale Style-Konfiguration
        """
        self.invoice = invoice
        self.layout = layout or LayoutConfig()
        self.style = style or StyleConfig()
        
        self._canvas: Optional[canvas.Canvas] = None
        self._width: float = 0
        self._height: float = 0
        self._y: float = 0
        self._page_number: int = 0
        
        # Tabellen-Koordinaten
        self._table_left: float = 0
        self._table_right: float = 0
        self._table_top_y: float = 0
        self._table_bottom_y: float = 0
        
        # Spaltengrenzen (X-Koordinaten der vertikalen Linien)
        self._col_desc_end: float = 0
        self._col_qty_end: float = 0
        self._col_unit_end: float = 0
        
        # Textpositionen (rechtsbündig mit Padding)
        self._col_qty_text_x: float = 0
        self._col_unit_text_x: float = 0
        self._col_amount_text_x: float = 0
    
    def generate(self, output_path: str | Path) -> Path:
        """
        Generiert die PDF-Rechnung.
        
        Args:
            output_path: Pfad für die Ausgabedatei
        
        Returns:
            Pfad zur generierten PDF-Datei
        
        Raises:
            ValueError: Bei ungültigen Rechnungsdaten
            IOError: Bei Schreibfehlern
        """
        output_path = Path(output_path)
        
        # Validierung
        warnings = self.invoice.validate()
        if warnings:
            # Nur loggen, nicht abbrechen
            for warning in warnings:
                print(f"Warnung: {warning}")
        
        # Canvas initialisieren
        self._canvas = canvas.Canvas(str(output_path), pagesize=A4)
        self._width, self._height = A4
        
        # Tabellenkoordinaten berechnen
        self._table_left = self.layout.margin_x
        self._table_right = self._width - self.layout.margin_x
        table_width = self._table_right - self._table_left
        
        # Spaltenbreiten (von links nach rechts)
        # | Leistung (55%) | Menge (12%) | Einzelpreis (16%) | Betrag (17%) |
        col_desc_width = table_width * 0.55
        col_qty_width = table_width * 0.12
        col_unit_width = table_width * 0.16
        col_amount_width = table_width * 0.17
        
        # Spaltengrenzen (X-Koordinaten der vertikalen Linien)
        self._col_desc_end = self._table_left + col_desc_width
        self._col_qty_end = self._col_desc_end + col_qty_width
        self._col_unit_end = self._col_qty_end + col_unit_width
        
        # Textpositionen (rechtsbündig innerhalb der Spalte, mit Padding)
        padding = 3 * mm
        self._col_qty_text_x = self._col_qty_end - padding
        self._col_unit_text_x = self._col_unit_end - padding
        self._col_amount_text_x = self._table_right - padding
        
        # Erste Seite starten
        self._start_new_page()
        
        # Inhalt rendern
        self._render_header()
        self._render_invoice_info()
        self._render_client_info()
        self._render_items_table()
        self._render_totals()
        self._render_notes()
        self._render_payment_info()
        
        # Speichern
        self._canvas.save()
        
        return output_path
    
    def _start_new_page(self) -> None:
        """Startet eine neue Seite."""
        if self._page_number > 0:
            self._canvas.showPage()
        
        self._page_number += 1
        self._y = self._height - self.layout.margin_top
        
        # Seitenzahl (ab Seite 2)
        if self._page_number > 1:
            self._render_page_number()
    
    def _render_page_number(self) -> None:
        """Rendert die Seitenzahl."""
        self._canvas.setFont(self.style.font_regular, self.layout.font_size_small)
        self._canvas.setFillColor(self.style.secondary_color)
        
        page_text = f"{self.invoice.t('page')} {self._page_number}"
        self._canvas.drawRightString(
            self._table_right,
            self.layout.margin_bottom / 2,
            page_text
        )
        self._canvas.setFillColor(colors.black)
    
    def _render_header(self) -> None:
        """Rendert den Kopfbereich mit Logo und Ausstellerdaten."""
        c = self._canvas
        issuer = self.invoice.issuer
        right_x = self._width - self.layout.margin_x
        
        # Logo (höher positioniert)
        if self.invoice.logo_path and os.path.exists(self.invoice.logo_path):
            try:
                img = ImageReader(self.invoice.logo_path)
                logo_y = self._y - self.layout.logo_height + 8 * mm  # 8mm höher
                c.drawImage(
                    img,
                    self.layout.margin_x,
                    logo_y,
                    width=self.layout.logo_width,
                    height=self.layout.logo_height,
                    mask="auto",
                    preserveAspectRatio=True,
                    anchor="sw",
                )
            except Exception as e:
                print(f"Warnung: Logo konnte nicht geladen werden: {e}")
        
        # Ausstellername (fett)
        c.setFont(self.style.font_bold, self.layout.font_size_header)
        c.drawRightString(right_x, self._y, issuer.address.name)
        
        # Ausstelleradresse
        c.setFont(self.style.font_regular, self.layout.font_size_normal)
        y = self._y - self.layout.line_height
        
        for line in issuer.address.to_lines():
            c.drawRightString(right_x, y, line)
            y -= self.layout.line_height * 0.8
        
        # Kontaktdaten
        if issuer.phone:
            c.drawRightString(right_x, y, f"{self.invoice.t('phone')}: {issuer.phone}")
            y -= self.layout.line_height * 0.8
        
        if issuer.email:
            c.drawRightString(right_x, y, issuer.email)
            y -= self.layout.line_height * 0.8
        
        if issuer.website:
            c.drawRightString(right_x, y, issuer.website)
            y -= self.layout.line_height * 0.8
        
        # Steuernummer / USt-IdNr
        if issuer.tax_number:
            c.drawRightString(right_x, y, f"{self.invoice.t('tax_number')}: {issuer.tax_number}")
            y -= self.layout.line_height * 0.8
        
        if issuer.vat_id:
            c.drawRightString(right_x, y, f"{self.invoice.t('vat_id')}: {issuer.vat_id}")
        
        # Y-Position nach Logo aktualisieren
        self._y -= (self.layout.logo_height + self.layout.section_gap * 0.5)
    
    def _render_invoice_info(self) -> None:
        """Rendert die Rechnungsinformationen (Titel, Nummer, Datum)."""
        c = self._canvas
        meta = self.invoice.metadata
        
        # Titel
        title = meta.title or self.invoice.t("invoice")
        c.setFont(self.style.font_bold, self.layout.font_size_title)
        c.drawString(self.layout.margin_x, self._y, title)
        
        # Rechnungsdaten
        self._y -= self.layout.section_gap * 0.8
        c.setFont(self.style.font_regular, self.layout.font_size_normal)
        
        c.drawString(
            self.layout.margin_x,
            self._y,
            f"{self.invoice.t('invoice_number')}: {meta.number}"
        )
        self._y -= self.layout.line_height
        
        c.drawString(
            self.layout.margin_x,
            self._y,
            f"{self.invoice.t('invoice_date')}: {format_date(meta.date, self.invoice.language)}"
        )
        self._y -= self.layout.line_height
        
        # Leistungsdatum oder -zeitraum
        if meta.service_period_start and meta.service_period_end:
            period_str = (
                f"{format_date(meta.service_period_start, self.invoice.language)} - "
                f"{format_date(meta.service_period_end, self.invoice.language)}"
            )
            c.drawString(
                self.layout.margin_x,
                self._y,
                f"{self.invoice.t('service_date')}: {period_str}"
            )
        else:
            c.drawString(
                self.layout.margin_x,
                self._y,
                f"{self.invoice.t('service_date')}: {format_date(meta.service_date, self.invoice.language)}"
            )
        
        self._y -= self.layout.section_gap
    
    def _render_client_info(self) -> None:
        """Rendert die Kundeninformationen."""
        c = self._canvas
        client = self.invoice.client
        
        # Überschrift
        c.setFont(self.style.font_bold, self.layout.font_size_normal + 1)
        c.drawString(self.layout.margin_x, self._y, self.invoice.t("bill_to"))
        
        # Kundendaten
        self._y -= self.layout.line_height * 1.2
        c.setFont(self.style.font_regular, self.layout.font_size_normal)
        
        c.drawString(self.layout.margin_x, self._y, client.address.name)
        self._y -= self.layout.line_height * 0.8
        
        for line in client.address.to_lines():
            c.drawString(self.layout.margin_x, self._y, line)
            self._y -= self.layout.line_height * 0.8
        
        self._y -= self.layout.section_gap * 0.5
    
    def _render_items_table(self) -> None:
        """Rendert die Positionstabelle."""
        # Mehr Abstand vor der Tabelle
        self._y -= self.layout.section_gap
        
        self._table_top_y = self._y
        self._render_table_header()
        
        for item in self.invoice.items:
            self._render_table_item(item)
        
        # Abschließende Linien
        self._draw_table_lines()
    
    def _render_table_header(self) -> None:
        """Rendert den Tabellenkopf."""
        c = self._canvas
        padding = 3 * mm
        
        # Speichere die Y-Position für die obere Grenze
        header_top_y = self._y
        
        # Header-Text (vertikal zentriert in der Header-Zeile)
        self._y -= 5 * mm
        c.setFont(self.style.font_bold, self.layout.font_size_normal)
        
        # Leistung linksbündig
        c.drawString(self._table_left + padding, self._y, self.invoice.t("service"))
        
        # Menge, Einzelpreis, Betrag rechtsbündig in ihrer Spalte
        c.drawRightString(self._col_qty_text_x, self._y, self.invoice.t("quantity"))
        c.drawRightString(self._col_unit_text_x, self._y, self.invoice.t("unit_price"))
        c.drawRightString(self._col_amount_text_x, self._y, self.invoice.t("amount"))
        
        # Untere Grenze des Headers
        self._y -= 4 * mm
        header_bottom_y = self._y
        
        # Horizontale Linie unter dem Header (komplett durchgezogen)
        c.setStrokeColor(self.style.line_color)
        c.setLineWidth(self.style.table_line_width)  # Dünnere Linie
        c.line(self._table_left, header_bottom_y, self._table_right, header_bottom_y)
        
        # Vertikale Linien im Header
        c.setLineWidth(self.style.table_line_width)
        c.line(self._col_desc_end, header_top_y, self._col_desc_end, header_bottom_y)
        c.line(self._col_qty_end, header_top_y, self._col_qty_end, header_bottom_y)
        c.line(self._col_unit_end, header_top_y, self._col_unit_end, header_bottom_y)
        
        # Y-Position für erste Datenzeile
        self._y -= 5 * mm
        c.setFont(self.style.font_regular, self.layout.font_size_normal)
        
        # Speichere die Y-Position für vertikale Linien im Datenbereich
        self._table_top_y = self._y + 5 * mm
    
    def _render_table_item(self, item: InvoiceItem) -> None:
        """Rendert eine einzelne Tabellenposition."""
        c = self._canvas
        padding = 3 * mm
        
        # Text umbrechen
        wrapped = textwrap.wrap(
            item.description,
            width=self.layout.description_wrap_width
        ) or [""]
        
        first_line = True
        for line in wrapped:
            # Seitenumbruch prüfen
            if self._y < self.layout.page_break_threshold:
                self._draw_table_lines()
                self._start_new_page()
                self._table_top_y = self._y
                self._render_table_header()
            
            # Beschreibung (linksbündig mit Padding)
            c.drawString(self._table_left + padding, self._y, line)
            
            # Nur in der ersten Zeile: Menge, Preis, Betrag
            if first_line:
                c.drawRightString(
                    self._col_qty_text_x,
                    self._y,
                    format_quantity(item.quantity, item.unit)
                )
                c.drawRightString(
                    self._col_unit_text_x,
                    self._y,
                    format_currency(item.unit_price, locale=self.invoice.language)
                )
                c.drawRightString(
                    self._col_amount_text_x,
                    self._y,
                    format_currency(item.net_amount, locale=self.invoice.language)
                )
                first_line = False
            
            self._y -= self.layout.table_row_height
        
        self._table_bottom_y = self._y
    
    def _draw_table_lines(self) -> None:
        """Zeichnet die vertikalen Tabellenlinien."""
        c = self._canvas
        c.setStrokeColor(self.style.line_color)
        c.setLineWidth(self.style.table_line_width)
        
        # Nur vertikale Linien zwischen den Spalten
        for x in [self._col_desc_end, self._col_qty_end, self._col_unit_end]:
            c.line(x, self._table_top_y, x, self._table_bottom_y + 2 * mm)
    
    def _render_totals(self) -> None:
        """Rendert die Summen."""
        c = self._canvas
        
        self._y -= self.layout.section_gap * 0.5
        
        # Bei MwSt: Zwischensumme und MwSt-Zeilen
        if self.invoice.vat_mode != VATMode.NONE and self.invoice.total_vat > 0:
            c.setFont(self.style.font_regular, self.layout.font_size_normal)
            
            # Zwischensumme
            c.drawRightString(self._col_unit_text_x, self._y, f"{self.invoice.t('subtotal')}:")
            c.drawRightString(
                self._col_amount_text_x,
                self._y,
                format_currency(self.invoice.subtotal, locale=self.invoice.language)
            )
            self._y -= self.layout.line_height
            
            # MwSt nach Sätzen aufgeschlüsselt
            for rate, amount in self.invoice.vat_summary.items():
                c.drawRightString(self._col_unit_text_x, self._y, f"{self.invoice.t('vat')} {rate}%:")
                c.drawRightString(
                    self._col_amount_text_x,
                    self._y,
                    format_currency(amount, locale=self.invoice.language)
                )
                self._y -= self.layout.line_height
        
        # Gesamtsumme (fett, leicht größer)
        c.setFont(self.style.font_bold, self.layout.font_size_normal + 1)
        c.drawRightString(self._col_unit_text_x, self._y, f"{self.invoice.t('total')}:")
        c.drawRightString(
            self._col_amount_text_x,
            self._y,
            format_currency(self.invoice.total, locale=self.invoice.language)
        )
        
        self._y -= self.layout.section_gap
    
    def _render_notes(self) -> None:
        """Rendert Hinweise (z.B. Kleinunternehmer-Hinweis)."""
        # Zusätzliche Notizen (ohne Kleinunternehmer-Hinweis, der kommt jetzt in _render_payment_info)
        if self.invoice.metadata.notes:
            c = self._canvas
            c.setFont(self.style.font_regular, self.layout.font_size_small)
            for note in self.invoice.metadata.notes:
                wrapped = textwrap.wrap(note, width=90)
                for line in wrapped:
                    if self._y < self.layout.page_break_threshold:
                        self._start_new_page()
                    c.drawString(self._table_left, self._y, line)
                    self._y -= self.layout.line_height * 0.8
                self._y -= self.layout.line_height * 0.5
    
    def _render_payment_info(self) -> None:
        """Rendert die Zahlungsinformationen."""
        c = self._canvas
        payment = self.invoice.payment
        meta = self.invoice.metadata
        
        # Seitenumbruch prüfen
        if self._y < self.layout.page_break_threshold + 30 * mm:
            self._start_new_page()
        
        # Mehr Abstand nach oben
        self._y -= self.layout.section_gap * 3
        
        # Kleinunternehmer-Hinweis über den Zahlungsinfos
        if self.invoice.vat_mode == VATMode.NONE:
            c.setFont(self.style.font_regular, self.layout.font_size_small)
            c.drawString(
                self._table_left,
                self._y,
                self.invoice.t("vat_note_small_business")
            )
            self._y -= self.layout.section_gap  # Abstand zu Zahlungsinfos
        
        c.setFont(self.style.font_regular, self.layout.font_size_small)
        line_gap = self.layout.line_height * 1.2
        
        # Zahlungsziel
        c.drawString(
            self._table_left,
            self._y,
            f"{self.invoice.t('payment_terms')}: {meta.due_days} {self.invoice.t('days')}"
        )
        self._y -= line_gap
        
        c.drawString(
            self._table_left,
            self._y,
            f"{self.invoice.t('due_date')}: {format_date(meta.due_date, self.invoice.language)}"
        )
        self._y -= line_gap
        
        # Bankverbindung
        if payment.account_holder:
            c.drawString(
                self._table_left,
                self._y,
                f"{self.invoice.t('account_holder')}: {payment.account_holder}"
            )
            self._y -= line_gap
        
        if payment.iban:
            c.drawString(self._table_left, self._y, f"IBAN: {payment.iban}")
            self._y -= line_gap
        
        if payment.bic:
            c.drawString(self._table_left, self._y, f"BIC: {payment.bic}")
            self._y -= line_gap
        
        if payment.bank_name:
            c.drawString(self._table_left, self._y, f"Bank: {payment.bank_name}")
        
        if payment.payment_reference:
            self._y -= line_gap
            c.drawString(
                self._table_left,
                self._y,
                f"Verwendungszweck: {payment.payment_reference}"
            )


# =============================================================================
# Legacy-Kompatibilitätsfunktion
# =============================================================================

def generate_invoice_pdf(
    output_pdf_path: str,
    logo_path: str | None,
    issuer: dict,
    client: dict,
    invoice: dict,
    items: list,
    payment: dict,
) -> str:
    """
    Legacy-Funktion für Abwärtskompatibilität.
    
    Diese Funktion behält die ursprüngliche API bei, nutzt aber intern
    die neue, verbesserte Implementierung.
    
    Args:
        output_pdf_path: Pfad für die Ausgabedatei
        logo_path: Optionaler Pfad zum Logo
        issuer: Ausstellerdaten als Dictionary
        client: Kundendaten als Dictionary
        invoice: Rechnungsdaten als Dictionary
        items: Liste der Positionen als Dictionaries
        payment: Zahlungsinformationen als Dictionary
    
    Returns:
        Pfad zur generierten PDF-Datei
    """
    # Aussteller konvertieren
    issuer_address = Address(
        name=issuer.get("name", ""),
        additional_lines=issuer.get("address_lines", []),
    )
    issuer_obj = Issuer(
        address=issuer_address,
        phone=issuer.get("phone", ""),
        email=issuer.get("email", ""),
        tax_number=issuer.get("tax_number", ""),
        vat_id=issuer.get("vat_id", ""),
    )
    
    # Kunde konvertieren
    client_address = Address(
        name=client.get("name", ""),
        additional_lines=client.get("address_lines", []),
    )
    client_obj = Client(address=client_address)
    
    # Metadaten konvertieren
    invoice_date = None
    if invoice.get("date"):
        try:
            invoice_date = datetime.strptime(invoice["date"], "%d.%m.%Y")
        except ValueError:
            pass
    
    service_date = None
    if invoice.get("service_date"):
        try:
            service_date = datetime.strptime(invoice["service_date"], "%d.%m.%Y")
        except ValueError:
            pass
    
    metadata = InvoiceMetadata(
        number=invoice.get("number", ""),
        date=invoice_date,
        service_date=service_date,
        title=invoice.get("title", ""),
        due_days=14,
    )
    
    # Positionen konvertieren
    items_obj = [InvoiceItem.from_dict(item) for item in items]
    
    # Zahlungsinfo konvertieren
    payment_obj = PaymentInfo(
        account_holder=payment.get("account_holder", ""),
        iban=payment.get("iban", ""),
        bic=payment.get("bic", ""),
    )
    
    # VAT-Modus
    vat_mode = VATMode.NONE
    if not invoice.get("show_vat_note", True):
        vat_mode = VATMode.EXCLUSIVE
    
    # Rechnung erstellen
    invoice_obj = Invoice(
        issuer=issuer_obj,
        client=client_obj,
        metadata=metadata,
        items=items_obj,
        payment=payment_obj,
        vat_mode=vat_mode,
        logo_path=logo_path,
    )
    
    # PDF generieren
    generator = InvoicePDFGenerator(invoice_obj)
    result_path = generator.generate(output_pdf_path)
    
    return str(result_path)


# =============================================================================
# Beispiel / Demo
# =============================================================================

if __name__ == "__main__":
    # Demo-Rechnung mit der neuen API
    demo_invoice = Invoice(
        issuer=Issuer(
            address=Address(
                name="Max Mustermann",
                street="Musterstraße 123",
                postal_code="12345",
                city="Musterstadt",
            ),
            phone="+49 123 456789",
            email="kontakt@mustermann.de",
            tax_number="123/456/78901",
        ),
        client=Client(
            address=Address(
                name="Firma Beispiel GmbH",
                street="Beispielweg 42",
                postal_code="54321",
                city="Beispielstadt",
            ),
        ),
        metadata=InvoiceMetadata(
            number="2025-001",
            title="Rechnung",
            due_days=14,
            notes=[],
        ),
        items=[
            InvoiceItem(
                description="Webentwicklung - Frontend-Implementierung",
                quantity=Decimal("10"),
                unit_price=Decimal("85.00"),
                unit="Std.",
            ),
            InvoiceItem(
                description="Hosting & Domain (monatlich)",
                quantity=Decimal("1"),
                unit_price=Decimal("29.90"),
            ),
            InvoiceItem(
                description="WordPress-Theme Anpassung und individuelle Styling-Änderungen nach Kundenwunsch",
                quantity=Decimal("5"),
                unit_price=Decimal("75.00"),
                unit="Std.",
            ),
        ],
        payment=PaymentInfo(
            account_holder="Max Mustermann",
            iban="DE89 3704 0044 0532 0130 00",
            bic="COBADEFFXXX",
            bank_name="Commerzbank",
        ),
        vat_mode=VATMode.NONE,
        language=Language.DE,
        logo_path="/mnt/user-data/uploads/logo.png",
    )
    
    # PDF generieren
    generator = InvoicePDFGenerator(demo_invoice)
    output_path = generator.generate("/home/claude/demo_rechnung.pdf")
    print(f"Demo-Rechnung erstellt: {output_path}")
