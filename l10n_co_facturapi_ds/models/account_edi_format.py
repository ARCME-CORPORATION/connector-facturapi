import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DS_DOC_TYPE_CODE_MAP = {
    "support_doc": "05",
    "support_doc_credit_note": "95",
}


class AccountEdiFormatDS(models.Model):
    _inherit = "account.edi.format"

    def _get_move_applicability(self, move):
        self.ensure_one()
        if self.code == "facturapi_ds":
            if move.move_type not in ("out_invoice", "out_refund"):
                return
            if not move.company_id.l10n_co_ds_enabled:
                return
            return {
                "post": self._l10n_co_ds_post_invoices,
                "cancel": self._l10n_co_ds_cancel_invoices,
                "edi_content": self._l10n_co_ds_edi_content,
                "post_batching": lambda move: (move.move_type,),
                "cancel_batching": lambda move: (move.move_type,),
            }
        return super()._get_move_applicability(move)

    def _l10n_co_ds_post_invoices(self, moves):
        result = {}
        for move in moves:
            try:
                move._l10n_co_ds_post()
                result[move] = {"success": True}
            except Exception as e:
                _logger.error("DIAN DS post failed for %s: %s", move.name, e)
                result[move] = {
                    "success": False,
                    "error": str(e),
                    "blocking_level": "error",
                }
        return result

    def _l10n_co_ds_cancel_invoices(self, moves):
        result = {}
        for move in moves:
            try:
                move._l10n_co_ds_cancel()
                result[move] = {"success": True}
            except Exception as e:
                _logger.error("DIAN DS cancel failed for %s: %s", move.name, e)
                result[move] = {
                    "success": False,
                    "error": str(e),
                    "blocking_level": "error",
                }
        return result

    def _l10n_co_ds_edi_content(self, move):
        doc = move.l10n_co_ds_document_id
        if doc and doc.xml_signed:
            return base64.b64decode(doc.xml_signed)
        return b""

    def _build_facturapi_ds_payload(self, move):
        company = move.company_id
        partner = move.partner_id
        currency = move.currency_id or company.currency_id

        certificate = company.certificate_id
        cert_pem = ""
        key_pem = ""
        if certificate:
            cert_pem = self._to_pem_str(certificate.pem_certificate)
            if certificate.private_key_id:
                key_pem = self._to_pem_str(certificate.private_key_id.pem_key)

        sequence_range = self._get_active_sequence_range(move)
        resolution_number = ""
        resolution_number_from = 0
        resolution_number_to = 0
        technical_key = ""
        if sequence_range:
            resolution_number = getattr(sequence_range, "dian_ds_resolution_number", "") or ""
            resolution_number_from = getattr(sequence_range, "dian_ds_number_from", 0) or 0
            resolution_number_to = getattr(sequence_range, "dian_ds_number_to", 0) or 0
            technical_key = getattr(sequence_range, "dian_ds_technical_key", "") or ""

        doc_type = self._get_ds_document_type(move)
        doc_type_code = DS_DOC_TYPE_CODE_MAP.get(doc_type, "05")

        nit = ""
        if hasattr(company, "_get_nit"):
            nit = company._get_nit()

        lines = []
        for line in move.invoice_line_ids:
            tax_percent = 0.0
            tax_code = "01"
            for tax in line.tax_ids:
                tax_percent = float(tax.amount)
                tax_code = self._map_tax_code(tax)
                break
            lines.append({
                "line_number": line.sequence or 1,
                "item_code": line.product_id.default_code or "",
                "item_description": line.name,
                "quantity": float(line.quantity),
                "unit_code": getattr(line.product_uom_id, "l10n_co_code", None) or "94",
                "unit_name": line.product_uom_id.name or "Unidad",
                "price_unit": float(line.price_unit),
                "discount_percent": float(line.discount or 0),
                "discount_amount": 0.0,
                "tax_percent": tax_percent,
                "tax_amount": round(float(line.price_subtotal) * tax_percent / 100.0, 2),
                "tax_code": tax_code,
                "total": float(line.price_subtotal),
                "unspsc_code": "",
            })

        tax_totals = []
        for tax_line in move.line_ids.filtered(lambda l: l.tax_repartition_line_id):
            tax_totals.append({
                "tax_code": self._map_tax_code(tax_line.tax_repartition_line_id.tax_id),
                "tax_name": tax_line.tax_repartition_line_id.tax_id.name,
                "taxable_base": float(tax_line.tax_base_amount),
                "tax_amount": float(tax_line.balance),
            })

        environment = (
            getattr(company, "l10n_co_dian_environment", None)
            or getattr(company, "facturapi_environment", None)
            or "habilitacion"
        )

        prefix = getattr(move, "l10n_latam_document_number_prefix", None) or "DS"

        return {
            "company_id": getattr(company, "facturapi_company_id", None) or str(company.id),
            "document_type": doc_type,
            "document_type_code": doc_type_code,
            "environment": environment,
            "certificate_pem": cert_pem,
            "private_key_pem": key_pem,
            "software_id": getattr(company, "l10n_co_software_id", "") or "",
            "software_pin": getattr(company, "l10n_co_software_pin", "") or "",
            "software_nit": nit,
            "test_set_id": getattr(company, "l10n_co_test_set_id", "") or "",
            "prefix": prefix,
            "number": getattr(move, "l10n_latam_document_number", None) or "",
            "issue_date": fields.Date.to_string(move.invoice_date),
            "issue_time": getattr(move, "invoice_time", None) or "00:00:00",
            "due_date": fields.Date.to_string(move.invoice_date_due) if move.invoice_date_due else None,
            "currency": currency.name,
            "resolution_number": resolution_number,
            "resolution_number_from": resolution_number_from,
            "resolution_number_to": resolution_number_to,
            "technical_key": technical_key,
            "operation_type": "10",
            "invoice_type_code": doc_type_code,
            "notes": move.narration or "",
            "supplier": self._build_ds_party_dict(company.partner_id, company, is_supplier=True),
            "customer": self._build_ds_party_dict(partner, company, is_supplier=False),
            "payment_method_code": "1",
            "payment_due_date": fields.Date.to_string(move.invoice_date_due) if move.invoice_date_due else None,
            "lines": lines,
            "tax_totals": tax_totals,
            "line_extension_amount": float(move.amount_untaxed),
            "tax_exclusive_amount": float(move.amount_untaxed),
            "tax_inclusive_amount": float(move.amount_total),
            "payable_amount": float(move.amount_total),
            "profile_id": "DIAN 2.1: documento soporte en adquisiciones efectuadas a no obligados a facturar.",
            "customization_id": "10",
            "uuid_scheme_name": "CUDS-SHA384",
            "document_identifier_prefix": "DS",
        }

    def _get_ds_document_type(self, move):
        if move.move_type == "out_invoice":
            return "support_doc"
        elif move.move_type == "out_refund":
            return "support_doc_credit_note"
        return "support_doc"

    def _build_ds_party_dict(self, partner, company=None, is_supplier=False):
        fiscal_regime = getattr(partner, "l10n_co_fiscal_regime", "") or ""
        if not fiscal_regime and company:
            fiscal_regime = getattr(company, "l10n_co_fiscal_regime", "") or ""
        if is_supplier:
            return {
                "identification_type": getattr(partner.l10n_latam_identification_type_id, "l10n_co_code", None)
                or (getattr(partner.l10n_latam_identification_type_id, "code", None) if partner.l10n_latam_identification_type_id else "")
                or "",
                "identification_number": partner.vat or "",
                "dv": getattr(partner, "l10n_co_dv", "") or "",
                "name": partner.commercial_company_name or partner.name or "",
                "commercial_name": partner.display_name or "",
                "tax_scheme_id": "ZZ",
                "tax_scheme_name": "No aplica",
                "tax_level_code": str(getattr(partner, "l10n_co_ds_tax_level_code", "") or "O-23;O-47"),
                "fiscal_regime": str(fiscal_regime),
                "additional_account_id": "1",
                "address": {
                    "address_line": partner.street or "",
                    "city_code": getattr(partner.city_id, "l10n_co_code", "") if partner.city_id else "",
                    "city_name": partner.city or "",
                    "state_code": getattr(partner.state_id, "l10n_co_code", None)
                    or (partner.state_id.code if partner.state_id else "")
                    or "",
                    "state_name": partner.state_id.name or "",
                    "country_code": partner.country_id.code or "CO",
                    "postal_code": partner.zip or "",
                    "phone": partner.phone or "",
                    "email": partner.email or "",
                },
            }
        else:
            return {
                "identification_type": getattr(partner.l10n_latam_identification_type_id, "l10n_co_code", None)
                or (getattr(partner.l10n_latam_identification_type_id, "code", None) if partner.l10n_latam_identification_type_id else "")
                or "",
                "identification_number": partner.vat or "",
                "dv": getattr(partner, "l10n_co_dv", "") or "",
                "name": partner.commercial_company_name or partner.name or "",
                "commercial_name": partner.display_name or "",
                "tax_scheme_id": "01",
                "tax_scheme_name": "IVA",
                "tax_level_code": str(getattr(company, "l10n_co_tax_level_code", "0") or "0") if company else "0",
                "fiscal_regime": str(fiscal_regime),
                "additional_account_id": "2",
                "address": {
                    "address_line": partner.street or "",
                    "city_code": getattr(partner.city_id, "l10n_co_code", "") if partner.city_id else "",
                    "city_name": partner.city or "",
                    "state_code": getattr(partner.state_id, "l10n_co_code", None)
                    or (partner.state_id.code if partner.state_id else "")
                    or "",
                    "state_name": partner.state_id.name or "",
                    "country_code": partner.country_id.code or "CO",
                    "postal_code": partner.zip or "",
                    "phone": partner.phone or "",
                    "email": partner.email or "",
                },
            }

    def _get_active_sequence_range(self, move):
        sequence = getattr(move, "l10n_latam_document_number_id", None)
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

    def _to_pem_str(self, value):
        if not value:
            return ""
        if isinstance(value, bytes):
            decoded = value.decode("utf-8", errors="replace")
            if decoded.startswith("-----"):
                return decoded
            try:
                return base64.b64decode(decoded).decode("utf-8")
            except Exception:
                return decoded
        if str(value).startswith("-----"):
            return str(value)
        try:
            return base64.b64decode(str(value)).decode("utf-8")
        except Exception:
            return str(value)

    @staticmethod
    def _map_tax_code(tax):
        l10n_co_code = getattr(tax, "l10n_co_code", None)
        if l10n_co_code:
            return l10n_co_code
        mapping = {0: "01", 5: "05", 19: "19"}
        try:
            return mapping.get(int(tax.amount), "01")
        except (ValueError, TypeError):
            return "01"
