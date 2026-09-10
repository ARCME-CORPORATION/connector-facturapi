import base64
import io
import json
import logging
import re
import time
import zipfile
from datetime import datetime, timedelta, timezone

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DOC_TYPE_CODE_MAP = {
    "invoice": "01",
    "credit_note": "91",
    "debit_note": "92",
    "support_doc": "05",
    "support_doc_credit_note": "95",
    "support_doc_debit_note": "96",
    "payroll": "04",
}

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text):
    """Remove HTML tags, returning plain text.  DIAN cbc:Note must not contain XML elements."""
    if not text:
        return ""
    return _HTML_TAG_RE.sub("", str(text)).strip()


_IDENT_TYPE_MAP = {
    "national_citizen_id": "11",
    "id_card": "11",
    "niup_id": "11",
    "civil_registration": "13",
    "foreign_colombian_card": "22",
    "foreign_resident_card": "21",
    "foreign_id_card": "22",
    "vat": "31",
    "rut": "31",
    "passport": "41",
    "PEP": "47",
    "PPT": "48",
    "external_id": "50",
}

_TAX_CODE_TO_NAME = {
    "01": "IVA",
    "02": "IC",
    "03": "ICA",
    "04": "INC",
    "05": "ReteIVA",
    "06": "ReteFuente",
    "07": "ReteICA",
    "08": "ReteCREE",
}


def _clean_prefix(prefix):
    import re
    cleaned = re.sub(r"%\([^)]*\)s", "", prefix).strip("/- ")
    return cleaned[:10]


def _get_identification_type(partner):
    id_type = partner.l10n_latam_identification_type_id
    if not id_type:
        return ""
    doc_code = getattr(id_type, "l10n_co_document_code", "") or ""
    return _IDENT_TYPE_MAP.get(doc_code, "")


def _get_operation_type(doc_type, move):
    if doc_type == "credit_note":
        return "20" if move.reversed_entry_id else "22"
    if doc_type == "debit_note":
        return "30" if move.debit_origin_id else "32"
    return "10"


def _map_tax_code(tax):
    dian_type = getattr(tax, "connector_dian_tax_type", None)
    if dian_type:
        return dian_type
    name = (tax.name or "").lower()
    if "iva" in name or "vat" in name:
        return "01"
    if "inc" in name:
        return "04"
    try:
        return {0: "01", 5: "01"}.get(int(tax.amount), "01")
    except (ValueError, TypeError):
        return "01"


def _map_tax_name(tax):
    return _TAX_CODE_TO_NAME.get(_map_tax_code(tax), "IVA")


def _build_party_dict(partner, company=None, is_supplier=False):
    dv = getattr(partner, "l10n_co_verification_digit", "") or ""
    vat = (partner.vat or "").strip()
    if "-" in vat:
        vat = vat.rsplit("-", 1)[0]
    is_company = getattr(partner, "is_company", False)
    additional_account_id = "1" if is_company else "2"
    ident_type_code = _get_identification_type(partner)
    if ident_type_code == "31":
        identification_scheme_name = "31"
        identification_scheme_id = dv
    else:
        identification_scheme_name = "13"
        identification_scheme_id = ""
    if is_supplier:
        fiscal_regime = partner.connector_dian_fiscal_regime or "O-15"
        tax_level_code = partner.connector_dian_fiscal_regime or "O-15"
    else:
        fiscal_regime = partner.connector_dian_fiscal_regime or ""
        tax_level_code = partner.connector_dian_fiscal_regime or ""
        if not tax_level_code:
            tax_level_code = "R-99-PN" if not is_company else "O-23"
        if not fiscal_regime:
            fiscal_regime = tax_level_code
    ciiu_code = ""
    economic_activity = partner.l10n_co_economic_activity_id
    if economic_activity and economic_activity.code:
        ciiu_code = economic_activity.code
    return {
        "identification_type": ident_type_code,
        "identification_number": vat,
        "identification_scheme_name": identification_scheme_name,
        "identification_scheme_id": identification_scheme_id,
        "dv": dv,
        "additional_account_id": additional_account_id,
        "name": partner.commercial_company_name or partner.name or "",
        "commercial_name": partner.display_name or "",
        "ciiu_code": ciiu_code,
        "tax_scheme_id": "01",
        "tax_scheme_name": "IVA",
        "tax_level_code": str(tax_level_code),
        "fiscal_regime": str(fiscal_regime),
        "tax_responsibility": partner.connector_dian_tax_responsibility or "",
        "address": {
            "address_line": partner.street or "",
            "city_code": (
                getattr(partner.city_id, "connector_dane_code", "")
                if partner.city_id
                else ""
            ),
            "city_name": partner.city or "",
            "state_code": getattr(partner.state_id, "connector_dane_code", "")
            or (partner.state_id.code if partner.state_id else "")
            or "",
            "state_name": partner.state_id.name or "",
            "country_code": partner.country_id.code or "CO",
            "postal_code": partner.zip or "",
            "phone": partner.phone or "",
            "email": partner.email or "",
        },
    }


def _get_document_type(move):
    if move.move_type == "out_invoice":
        if move.debit_origin_id:
            return "debit_note"
        return "invoice"
    if move.move_type == "out_debit":
        return "debit_note"
    if move.move_type == "out_refund":
        return "credit_note"
    if move.move_type == "in_invoice":
        if move.debit_origin_id:
            return "debit_note"
        return "support_doc"
    if move.move_type == "in_refund":
        return "support_doc_credit_note"
    return "invoice"


class FacturapiDocument(models.Model):
    _name = "facturapi.document"
    _description = "FacturAPI DIAN Document"
    _rec_name = "name"
    _order = "create_date desc"

    name = fields.Char(string="Document Reference", readonly=True)
    move_id = fields.Many2one(
        "account.move", string="Invoice", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one("res.company", string="Company", required=True)

    state = fields.Selection(
        [
            ("to_send", "To Send"),
            ("processing", "Processing"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="to_send",
        required=True,
        copy=False,
    )
    is_cancel = fields.Boolean(string="Cancel Document", default=False, copy=False)
    connector_dian_accepted_datetime = fields.Datetime(
        string="DIAN Accepted At", readonly=True, copy=False
    )
    submit_request_at = fields.Datetime(
        string="Submit Request At", readonly=True, copy=False
    )
    task_ready_at = fields.Datetime(
        string="Task Ready At", readonly=True, copy=False
    )
    result_received_at = fields.Datetime(
        string="Result Received At", readonly=True, copy=False
    )

    task_id = fields.Char(string="FacturAPI Task ID", index=True, copy=False)
    document_type = fields.Selection(
        [
            ("invoice", "Factura Electronica de Venta"),
            ("credit_note", "Nota Credito"),
            ("debit_note", "Nota Debito"),
            ("support_doc", "Documento Soporte"),
            ("support_doc_credit_note", "Nota Credito DS"),
        ],
        string="Document Type",
    )

    cufe = fields.Char(string="CUFE/CUDE", copy=False)
    qr_code = fields.Text(string="QR Code (Base64)", copy=False)
    xml_signed = fields.Text(string="Signed XML", copy=False)
    pdf_file = fields.Text(string="PDF (Base64)", copy=False)
    application_response = fields.Text(string="Application Response", copy=False)
    attached_document = fields.Text(string="Attached Document", copy=False)

    dian_status = fields.Char(string="DIAN Status Code", copy=False)
    dian_message = fields.Text(string="DIAN Status Message", copy=False)
    error_message = fields.Text(string="Error Message", copy=False)
    dian_error_details = fields.Text(string="DIAN Error Details", copy=False)

    def _get_api_url(self):
        url = self.company_id.facturapi_api_url
        if not url:
            raise UserError(
                _("FacturAPI URL not configured for company %s") % self.company_id.name
            )
        return url.rstrip("/") + "/api/v1"

    def _get_headers(self):
        company = self.company_id
        token = f"{company.facturapi_company_id}:{company.facturapi_api_key}"
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _post_to_web_service(self):
        self.ensure_one()
        self.write({"submit_request_at": fields.Datetime.now()})
        move = self.move_id
        payload = self._build_facturapi_payload(move)

        base_url = self._get_api_url()
        url = f"{base_url}/documents/submit"
        response = requests.post(
            url, json=payload, headers=self._get_headers(), timeout=120
        )

        if response.status_code == 401:
            company = self.company_id
            raise UserError(_(
                "FacturAPI rechazó el acceso (401 Unauthorized). Verifique que el "
                "Company ID y la API Key de la empresa '%s' sean correctos y "
                "coincidan con los registrados en el backend FacturAPI.",
                company.name,
            ))

        if response.status_code == 404:
            detail = ""
            try:
                detail = response.json().get("detail", "")
            except Exception:
                detail = response.text[:300]
            detail_lower = detail.lower()
            if "certificate" in detail_lower or "certificado" in detail_lower:
                company = self.company_id
                self.write({
                    "state": "rejected",
                    "error_message": _("Certificado no registrado en el backend FacturAPI para la empresa '%s'") % company.name,
                })
                raise UserError(_(
                    "El certificado de la empresa '%s' no está registrado en el "
                    "backend FacturAPI (el backend respondió 404: %s). Por favor "
                    "cargue el certificado desde Configuración > Facturación "
                    "Electrónica > 'Enviar Certificado a API' y vuelva a intentar.",
                    company.name,
                    detail,
                ))

        if response.status_code >= 400:
            self.write({
                "state": "rejected",
                "error_message": _("Error de FacturAPI (%s): %s") % (
                    response.status_code,
                    response.text[:500],
                ),
            })
            raise UserError(_(
                "El backend FacturAPI respondió con error (%s). Consulte los "
                "detalles en la pestaña DIAN de la factura.",
                response.status_code,
            ))

        response.raise_for_status()
        result = response.json()

        self.write(
            {
                "task_id": result.get("task_id"),
                "state": "processing",
                "document_type": _get_document_type(move),
                "task_ready_at": fields.Datetime.now(),
            }
        )
        _logger.info(
            "FacturAPI task created: %s for invoice %s",
            result.get("task_id"),
            move.name,
        )

    # ------------------------------------------------------------------
    # Payload builder
    # ------------------------------------------------------------------

    def _get_active_sequence_range(self, move):
        sequence = getattr(move, "l10n_latam_document_number_id", None)
        if not sequence and move.journal_id:
            sequence = move.journal_id.sequence_id
        if not sequence:
            return self.env["ir.sequence.date_range"]
        invoice_date = move.invoice_date or fields.Date.context_today(self)
        range_obj = self.env["ir.sequence.date_range"]
        current_range = range_obj.search(
            [
                ("sequence_id", "=", sequence.id),
                ("date_from", "<=", invoice_date),
                ("date_to", ">=", invoice_date),
            ],
            limit=1,
        )
        if current_range:
            return current_range
        return range_obj.search(
            [("sequence_id", "=", sequence.id)],
            order="date_from desc",
            limit=1,
        )

    def _build_facturapi_payload(self, move):
        company = move.company_id
        partner = move.partner_id
        company_currency = company.currency_id
        invoice_currency = move.currency_id or company_currency
        # DIAN (Anexo 1.9) only accepts DocumentCurrencyCode=COP. Use company
        # currency amounts (already converted by Odoo) and keep the original
        # invoice currency + rate for PaymentExchangeRate.
        is_foreign = invoice_currency != company_currency
        # TRM = amount of company currency (COP) per unit of invoice currency.
        # invoice_currency_rate is the inverse (USD per COP); DIAN's
        # SourceCurrencyBaseRate/CalculationRate must be COP per USD.
        exchange_rate = 0.0
        if is_foreign:
            try:
                exchange_rate = float(
                    invoice_currency._convert(
                        1.0,
                        company_currency,
                        company,
                        move.invoice_date or fields.Date.context_today(self),
                    )
                )
            except Exception:
                inv_rate = float(
                    getattr(move, "invoice_currency_rate", None) or 0.0
                )
                if inv_rate:
                    exchange_rate = round(1.0 / inv_rate, 6)

        sequence_range = self._get_active_sequence_range(move)
        resolution_number = ""
        resolution_number_from = 0
        resolution_number_to = 0
        resolution_date_from = ""
        resolution_date_to = ""
        technical_key = ""
        if sequence_range:
            resolution_number = (
                getattr(sequence_range, "dian_resolution_number", "") or ""
            )
            resolution_number_from = getattr(sequence_range, "dian_number_from", 0) or 0
            resolution_number_to = getattr(sequence_range, "dian_number_to", 0) or 0
            technical_key = getattr(sequence_range, "dian_technical_key", "") or ""
            resolution_date_from = fields.Date.to_string(
                sequence_range.dian_resolution_date
                or sequence_range.date_from
                or fields.Date.context_today(self)
            )
            resolution_date_to = fields.Date.to_string(
                sequence_range.dian_resolution_date_to
                or sequence_range.date_to
                or fields.Date.context_today(self)
            )

        doc_type = _get_document_type(move)
        doc_type_code = DOC_TYPE_CODE_MAP.get(doc_type, "01")

        lines = []
        from .account_tax import WITHHOLDING_CODES
        # DIAN does not accept notes/sections as invoice lines: omit them.
        invoice_lines = move.invoice_line_ids.filtered(
            lambda l: l.display_type not in ("line_note", "line_section")
        )
        for idx, line in enumerate(invoice_lines, start=1):
            qty = float(line.quantity)
            discount_pct = float(line.discount or 0)
            if is_foreign:
                # balance / tax amounts on aml are already in company currency (COP)
                line_total = round(abs(float(line.balance)), 2)
                disc_curr = abs(float(getattr(line, "discount_amount_currency", 0) or 0))
                if disc_curr and exchange_rate:
                    discount_amount = round(disc_curr * exchange_rate, 2)
                elif discount_pct and discount_pct < 100:
                    gross = line_total / (1.0 - discount_pct / 100.0)
                    discount_amount = round(gross - line_total, 2)
                else:
                    discount_amount = 0.0
                if qty:
                    price = round((line_total + discount_amount) / qty, 2)
                else:
                    price = 0.0
            else:
                price = float(line.price_unit)
                line_total = round(float(line.price_subtotal), 2)
                discount_amount = round(
                    qty * price * discount_pct / 100.0, 2
                )
            wh_percent = 0.0
            wh_code = ""
            wh_name = ""
            line_taxes = []
            for tax in line.tax_ids:
                if getattr(tax, "l10n_co_withholding_counterpart", False):
                    continue
                code = _map_tax_code(tax)
                if code in WITHHOLDING_CODES:
                    wh_code = code
                    wh_name = _map_tax_name(tax)
                    wh_percent = abs(float(tax.amount))
                else:
                    pct = float(tax.amount)
                    amt = round(line_total * pct / 100.0, 2)
                    line_taxes.append(
                        {
                            "tax_code": code,
                            "tax_name": _map_tax_name(tax),
                            "tax_percent": pct,
                            "tax_amount": amt,
                        }
                    )
            tax_percent = line_taxes[0]["tax_percent"] if line_taxes else 0.0
            tax_code = line_taxes[0]["tax_code"] if line_taxes else "01"
            tax_name = line_taxes[0]["tax_name"] if line_taxes else "IVA"
            tax_amount = line_taxes[0]["tax_amount"] if line_taxes else 0.0
            wh_amount = round(line_total * wh_percent / 100.0, 2) if wh_code else 0.0
            line_entry = {
                "line_number": idx,
                "item_code": line.product_id.default_code or "",
                "item_description": line.name,
                "quantity": qty,
                "barcode": line.product_id.barcode or "",
                "unit_code": getattr(line.product_uom_id, "connector_dian_unit_code", None)
                or getattr(line.product_uom_id, "l10n_co_code", None)
                or "EA",
                "unit_name": line.product_uom_id.name or "Unidad",
                "price_unit": price,
                "discount_percent": discount_pct,
                "discount_amount": discount_amount,
                "tax_percent": tax_percent,
                "tax_amount": tax_amount,
                "tax_code": tax_code,
                "tax_name": tax_name,
                "taxes": line_taxes,
                "total": line_total,
                "unspsc_code": getattr(getattr(line.product_id.product_tmpl_id, "unspsc_code_id", None), "code", None) or line.product_id.connector_unspsc_code or "",
            }
            if wh_code:
                line_entry["withholding_tax_percent"] = wh_percent
                line_entry["withholding_tax_amount"] = wh_amount
                line_entry["withholding_tax_code"] = wh_code
                line_entry["withholding_tax_name"] = wh_name
            lines.append(line_entry)

        tax_totals = []
        withholding_tax_totals = []
        for tax_line in move.line_ids.filtered(lambda l: l.tax_repartition_line_id):
            tax = tax_line.tax_repartition_line_id.tax_id
            if getattr(tax, "l10n_co_withholding_counterpart", False):
                continue
            tax_code = _map_tax_code(tax)
            entry = {
                "tax_code": tax_code,
                "tax_name": _map_tax_name(tax),
                "taxable_base": abs(float(tax_line.tax_base_amount)),
                "tax_amount": abs(float(tax_line.balance)),
                "tax_percent": float(tax.amount),
            }
            if tax_code in WITHHOLDING_CODES:
                entry["tax_percent"] = abs(float(tax.amount))
                withholding_tax_totals.append(entry)
            else:
                tax_totals.append(entry)

        line_taxes = {}
        for l in lines:
            line_tax_list = l.get("taxes") or []
            if not line_tax_list:
                line_tax_list = [
                    {
                        "tax_code": "01",
                        "tax_name": "IVA",
                        "tax_percent": 0.0,
                        "tax_amount": 0.0,
                    }
                ]
            for lt in line_tax_list:
                tc = lt.get("tax_code") or "01"
                if tc in WITHHOLDING_CODES:
                    continue
                key = (tc, round(float(lt.get("tax_percent", 0.0) or 0.0), 2))
                if key not in line_taxes:
                    line_taxes[key] = {
                        "tax_code": tc,
                        "tax_name": _TAX_CODE_TO_NAME.get(
                            tc, lt.get("tax_name", "IVA")
                        ),
                        "taxable_base": 0.0,
                        "tax_amount": 0.0,
                        "tax_percent": float(lt.get("tax_percent", 0.0) or 0.0),
                    }
                line_taxes[key]["taxable_base"] += float(l["total"])
                line_taxes[key]["tax_amount"] += float(lt.get("tax_amount", 0.0) or 0.0)
        for key, entry in line_taxes.items():
            if not any(
                t.get("tax_code") == entry["tax_code"]
                and abs(float(t.get("tax_percent", 0.0) or 0.0) - entry["tax_percent"]) < 0.001
                for t in tax_totals
            ):
                tax_totals.append(entry)

        environment = (
            getattr(company, "connector_dian_environment", None)
            or "habilitacion"
        )

        issue_date_str = fields.Date.to_string(fields.Date.context_today(self))
        co_tz = timezone(timedelta(hours=-5))
        issue_time_str = datetime.now(co_tz).strftime("%H:%M:%S-05:00")

        due_date_str = fields.Date.to_string(
            max(move.invoice_date_due, fields.Date.context_today(self))
            if move.invoice_date_due
            else fields.Date.context_today(self)
        )

        software_nit_dv = (
            getattr(company.partner_id, "l10n_co_verification_digit", "") or ""
        )

        line_extension = round(sum(float(l["total"]) for l in lines), 2)
        tax_total_amount = round(
            sum(float(t.get("tax_amount") or 0) for t in tax_totals), 2
        )
        payload = {
            "company_id": getattr(company, "facturapi_company_id", None)
            or str(company.id),
            "document_type": doc_type,
            "document_type_code": doc_type_code,
            "environment": environment,
            "software_id": getattr(company, "connector_software_id", "") or "",
            "software_pin": getattr(company, "connector_software_pin", "") or "",
            "software_nit": company.partner_id.vat or "",
            "software_nit_dv": software_nit_dv,
            "test_set_id": (
                getattr(company, "connector_test_set_id", "") or ""
            ).replace(" ", ""),
            "prefix": _clean_prefix(
                getattr(move, "l10n_latam_document_number_prefix", None)
                or (
                    move.journal_id.sequence_id.prefix
                    if move.journal_id and move.journal_id.sequence_id
                    else ""
                )
                or ""
            ),
            "number": getattr(move, "l10n_latam_document_number", None)
            or (
                move.name.removeprefix(move.journal_id.sequence_id.prefix)
                if move.journal_id and move.journal_id.sequence_id and move.name
                else ""
            )
            or move.name
            or "",
            "issue_date": issue_date_str,
            "issue_time": issue_time_str,
            "due_date": due_date_str,
            "currency": company_currency.name,
            "resolution_number": resolution_number,
            "resolution_number_from": resolution_number_from,
            "resolution_number_to": resolution_number_to,
            "resolution_date_from": resolution_date_from,
            "resolution_date_to": resolution_date_to,
            "technical_key": technical_key,
            "operation_type": _get_operation_type(doc_type, move),
            "profile_execution_id": "1" if environment == "produccion" else "2",
            "invoice_type_code": getattr(move, "connector_dian_invoice_type_code", None) or doc_type_code,
            "credit_note_type_code": doc_type_code,
            "notes": _strip_html(move.narration),
            "supplier": _build_party_dict(
                company.partner_id, company, is_supplier=True
            ),
            "customer": _build_party_dict(partner, company, is_supplier=False),
            "payment_method_code": move.preferred_payment_method_line_id.journal_id.connector_dian_payment_method_code
            or move.journal_id.connector_dian_payment_method_code
            or "10",
            "payment_form_id": (
                move.invoice_payment_term_id.connector_dian_payment_form_id
                if move.invoice_payment_term_id
                and move.invoice_payment_term_id.connector_dian_payment_form_id
                else "1"
            ),
            "payment_due_date": due_date_str
            or fields.Date.to_string(fields.Date.context_today(self)),
            "uuid_scheme_id": "1" if environment == "produccion" else "2",
            "period_start": (
                fields.Date.to_string(move.invoice_date) if move.invoice_date else ""
            ),
            "period_end": (
                fields.Date.to_string(move.invoice_date) if move.invoice_date else ""
            ),
            "lines": lines,
            "tax_totals": tax_totals,
            "withholding_tax_totals": withholding_tax_totals,
            "line_extension_amount": line_extension,
            "tax_exclusive_amount": line_extension,
            "tax_inclusive_amount": round(line_extension + tax_total_amount, 2),
            "payable_amount": round(line_extension + tax_total_amount, 2),
        }
        if is_foreign and exchange_rate > 0:
            payload["original_currency"] = invoice_currency.name
            payload["exchange_rate"] = exchange_rate

        if doc_type == "credit_note" and move.reversed_entry_id:
            reversed_inv = move.reversed_entry_id
            payload["billing_reference_id"] = reversed_inv.name or ""
            payload["billing_reference_cufe"] = (
                getattr(reversed_inv, "connector_cufe", "") or ""
            )
            payload["billing_reference_date"] = (
                fields.Date.to_string(reversed_inv.invoice_date)
                if reversed_inv.invoice_date
                else ""
            )
            payload["discrepancy_response_code"] = "2"
            payload["discrepancy_description"] = "Anulación de la factura"

        if doc_type == "debit_note" and move.debit_origin_id:
            original_inv = move.debit_origin_id
            payload["billing_reference_id"] = original_inv.name or ""
            payload["billing_reference_cufe"] = (
                getattr(original_inv, "connector_cufe", "") or ""
            )
            payload["billing_reference_date"] = (
                fields.Date.to_string(original_inv.invoice_date)
                if original_inv.invoice_date
                else ""
            )
            payload["discrepancy_response_code"] = payload.get(
                "discrepancy_response_code", "1"
            )
            payload["discrepancy_description"] = payload.get(
                "discrepancy_description", "Intereses"
            )

        if doc_type in ("support_doc", "support_doc_credit_note"):
            supplier = payload.get("supplier", {})
            supplier["tax_scheme_id"] = "ZZ"
            supplier["tax_scheme_name"] = "No Aplica"
            payload["supplier"] = supplier
            partner = move.partner_id
            if partner.connector_dian_tax_responsibility:
                payload["customer"]["tax_responsibility"] = partner.connector_dian_tax_responsibility
            payment = payload.get("payment_method_code", "10")
            if not payment or payment == "1":
                payload["payment_method_code"] = "42"

        return payload

    def _check_task_status(self):
        self.ensure_one()
        if not self.task_id:
            return

        base_url = self._get_api_url()
        url = f"{base_url}/documents/{self.task_id}/status"

        response = requests.get(url, headers=self._get_headers(), timeout=120)

        if response.status_code == 401:
            raise UserError(_(
                "FacturAPI rechazó el acceso (401 Unauthorized). Verifique que el "
                "Company ID y la API Key de la empresa '%s' sean correctos y "
                "coincidan con los registrados en el backend FacturAPI.",
                self.company_id.name,
            ))

        response.raise_for_status()
        data = response.json()

        api_status = data.get("status", "")
        if api_status == "completed":
            self._fetch_and_process_result()
        elif api_status == "failed":
            self.write(
                {
                    "state": "rejected",
                    "error_message": data.get("error_message", "Processing failed"),
                }
            )

    def _wait_for_result(self, timeout=120, interval=5):
        self.ensure_one()
        if not self.task_id:
            return self.state
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._check_task_status()
            self.invalidate_recordset(["state", "error_message"])
            if self.state in ("accepted", "rejected"):
                return self.state
            time.sleep(interval)
        return self.state

    def _get_dian_zip_attachment(self):
        self.ensure_one()
        move = self.move_id
        prefix = (
            "DS"
            if self.document_type in ("support_doc", "support_doc_credit_note")
            else "FE"
        )
        number = move.name or "doc"
        zip_name = f"{prefix}_{number}.zip"

        existing = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", move.id),
                ("name", "=", zip_name),
            ],
            limit=1,
        )
        if existing:
            return existing
        if self.state != "accepted" or not (
            self.xml_signed and self.application_response
        ):
            return self.env["ir.attachment"]

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(
                f"{prefix}_{number}.xml",
                base64.b64decode(self.xml_signed),
            )
            zip_file.writestr(
                f"{prefix}_{number}_appresponse.xml",
                self.application_response.encode("utf-8"),
            )
            if self.pdf_file:
                try:
                    zip_file.writestr(
                        f"{prefix}_{number}.pdf",
                        base64.b64decode(self.pdf_file),
                    )
                except Exception:
                    _logger.warning(
                        "Skipping invalid PDF for DIAN ZIP %s", zip_name
                    )

        return self.env["ir.attachment"].create(
            {
                "name": zip_name,
                "type": "binary",
                "datas": base64.b64encode(buffer.getvalue()),
                "res_model": "account.move",
                "res_id": move.id,
                "mimetype": "application/zip",
            }
        )

    def _fetch_and_process_result(self):
        self.ensure_one()

        base_url = self._get_api_url()
        url = f"{base_url}/documents/{self.task_id}/result"

        response = requests.get(url, headers=self._get_headers(), timeout=120)
        if response.status_code == 409:
            _logger.info("Result not ready yet for %s (409)", self.name)
            return False

        if response.status_code == 401:
            raise UserError(_(
                "FacturAPI rechazó el acceso (401 Unauthorized). Verifique que el "
                "Company ID y la API Key de la empresa '%s' sean correctos y "
                "coincidan con los registrados en el backend FacturAPI.",
                self.company_id.name,
            ))

        response.raise_for_status()
        data = response.json()

        dian_status = data.get("dian_status", "")
        is_accepted = dian_status in ("00", "100")
        is_pending = dian_status == "67"

        write_vals = {
            "cufe": data.get("cufe_cude", ""),
            "qr_code": data.get("qr_code", ""),
            "xml_signed": data.get("xml_signed", ""),
            "pdf_file": data.get("pdf_file", ""),
            "application_response": data.get("application_response", ""),
            "dian_status": dian_status,
            "dian_error_details": data.get("dian_error_details", ""),
            "result_received_at": fields.Datetime.now(),
        }
        if is_accepted:
            write_vals["state"] = "accepted"
            write_vals["error_message"] = False
            write_vals["connector_dian_accepted_datetime"] = fields.Datetime.now()
        elif is_pending:
            write_vals["state"] = "processing"
            write_vals["error_message"] = "DIAN status 67: No events associated yet"
        else:
            write_vals["state"] = "rejected"
            write_vals["error_message"] = self._parse_dian_rejection(
                data.get("application_response", ""),
                data.get("dian_error_details", ""),
                dian_status,
            )
        self.write(write_vals)

        move = self.move_id
        move.write(
            {
                "connector_cufe": data.get("cufe_cude", ""),
                "connector_qr_code": data.get("qr_code", ""),
                "connector_xml_signed": data.get("xml_signed", ""),
                "connector_application_response": data.get("application_response", ""),
            }
        )

        xml_b64 = data.get("xml_signed", "")
        pdf_b64 = data.get("pdf_file", "")
        prefix = (
            "DS"
            if self.document_type in ("support_doc", "support_doc_credit_note")
            else "FE"
        )
        number = move.name or "doc"

        if xml_b64:
            existing_xml = self.env["ir.attachment"].search(
                [
                    ("res_model", "=", "account.move"),
                    ("res_id", "=", move.id),
                    ("name", "=like", f"{prefix}_{number}.xml"),
                ],
                limit=1,
            )
            if not existing_xml:
                self.env["ir.attachment"].create(
                    {
                        "name": f"{prefix}_{number}.xml",
                        "type": "binary",
                        "datas": xml_b64,
                        "res_model": "account.move",
                        "res_id": move.id,
                        "mimetype": "application/xml",
                    }
                )

        if pdf_b64:
            existing_pdf = self.env["ir.attachment"].search(
                [
                    ("res_model", "=", "account.move"),
                    ("res_id", "=", move.id),
                    ("name", "=like", f"{prefix}_{number}.pdf"),
                ],
                limit=1,
            )
            if not existing_pdf:
                self.env["ir.attachment"].create(
                    {
                        "name": f"{prefix}_{number}.pdf",
                        "type": "binary",
                        "datas": pdf_b64,
                        "res_model": "account.move",
                        "res_id": move.id,
                        "mimetype": "application/pdf",
                    }
                )

        if is_accepted:
            try:
                self._get_dian_zip_attachment()
            except Exception as e:
                _logger.warning("Failed to build DIAN ZIP for %s: %s", self.name, e)
            _logger.info(
                "DIAN accepted: task=%s cufe=%s",
                self.task_id,
                data.get("cufe_cude", "")[:16],
            )
        elif is_pending:
            _logger.info("DIAN pending: task=%s status=%s", self.task_id, dian_status)
        else:
            _logger.warning(
                "DIAN rejected: task=%s status=%s", self.task_id, dian_status
            )

    def _parse_dian_rejection(
        self, application_response, dian_error_details, dian_status
    ):
        messages = []

        if dian_error_details:
            try:
                details = (
                    json.loads(dian_error_details)
                    if isinstance(dian_error_details, str)
                    else dian_error_details
                )
                for item in details:
                    code = item.get("code", "")
                    desc = item.get("description", "")
                    if code and desc:
                        messages.append(f"{code}: {desc}")
                    elif desc:
                        messages.append(desc)
            except (ValueError, TypeError):
                pass

        if not messages and application_response:
            try:
                import xml.etree.ElementTree as ET

                root = ET.fromstring(application_response)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "StatusDescription" and elem.text:
                        messages.append(f"{dian_status}: {elem.text}")
                    elif tag == "ErrorMessage" and elem.text:
                        messages.append(elem.text)
            except Exception:
                pass

        if not messages:
            messages.append(f"DIAN status: {dian_status}")

        return "\n".join(messages)

    @api.model
    def _cron_check_dian_status(self):
        processing = self.search([("state", "=", "processing")])
        for doc in processing:
            try:
                doc._check_task_status()
            except Exception as e:
                _logger.error("Failed to check DIAN status for %s: %s", doc.name, e)
                doc.write({"error_message": str(e)[:2000]})

    def action_check_status(self):
        self.ensure_one()
        self._check_task_status()

    def action_fetch_result(self):
        self.ensure_one()
        if self.state == "processing" and self.task_id:
            self._fetch_and_process_result()

    def action_retry(self):
        self.ensure_one()
        self.write({"state": "to_send", "error_message": False, "task_id": False})
        self._post_to_web_service()
