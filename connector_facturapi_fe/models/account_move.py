import base64
import logging

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    connector_facturapi_document_id = fields.Many2one(
        "facturapi.document",
        string="DIAN Document",
        compute="_compute_connector_facturapi_document",
        store=True,
    )
    connector_facturapi_state = fields.Selection(
        related="connector_facturapi_document_id.state",
        string="DIAN Status",
    )
    connector_cufe = fields.Char(
        string="CUFE",
        size=128,
        readonly=True,
        copy=False,
    )
    connector_qr_code = fields.Text(
        string="QR Code",
        readonly=True,
        copy=False,
    )
    connector_xml_signed = fields.Text(
        string="XML Signed",
        readonly=True,
        copy=False,
    )
    connector_application_response = fields.Text(
        string="Application Response",
        readonly=True,
        copy=False,
    )
    connector_sequence_range_id = fields.Many2one(
        "ir.sequence.date_range",
        string="DIAN Sequence Range",
        readonly=True,
        copy=False,
    )

    @api.depends("edi_document_ids", "edi_document_ids.state")
    def _compute_connector_facturapi_document(self):
        for move in self:
            doc = self.env["facturapi.document"].search(
                [
                    ("move_id", "=", move.id),
                    ("is_cancel", "=", False),
                ],
                limit=1,
            )
            move.connector_facturapi_document_id = doc

    def _connector_facturapi_post(self):
        self.ensure_one()
        if self.connector_facturapi_document_id and self.connector_facturapi_document_id.state != "to_send":
            raise UserError(_("This invoice has already been sent to DIAN."))

        edi_format = self.env["account.edi.format"].search([("code", "=", "facturapi_invoice")], limit=1)
        if not edi_format:
            raise UserError(_("FacturAPI EDI format not found."))

        existing_edi_doc = self.edi_document_ids.filtered(
            lambda d: d.edi_format_id.code == "facturapi_invoice" and d.state == "to_send"
        )
        if not existing_edi_doc:
            existing_edi_doc = self.env["account.edi.document"].create(
                {
                    "move_id": self.id,
                    "edi_format_id": edi_format.id,
                    "state": "to_send",
                }
            )

        facturapi_doc = self.env["facturapi.document"].create(
            {
                "name": self.name or "/",
                "move_id": self.id,
                "company_id": self.company_id.id,
                "edi_document_id": existing_edi_doc.id,
                "document_type": edi_format._get_document_type(self),
                "state": "to_send",
            }
        )
        facturapi_doc._post_to_web_service()
        return True

    def _connector_facturapi_cancel(self):
        self.ensure_one()
        doc = self.connector_facturapi_document_id
        if not doc or doc.state != "accepted":
            raise UserError(_("No accepted DIAN document to cancel."))

        cancel_doc = self.env["facturapi.document"].create(
            {
                "name": f"{self.name or '/'} (Cancel)",
                "move_id": self.id,
                "company_id": self.company_id.id,
                "document_type": doc.document_type,
                "is_cancel": True,
                "state": "to_send",
            }
        )
        cancel_doc._post_to_web_service()
        return True

    def _connector_facturapi_check_status(self):
        self.ensure_one()
        doc = self.connector_facturapi_document_id
        if doc:
            doc._check_task_status()

    def action_send_to_dian(self):
        for move in self:
            move._connector_facturapi_post()

    def action_check_dian_status(self):
        for move in self:
            move._connector_facturapi_check_status()

    def action_cancel_dian(self):
        for move in self:
            move._connector_facturapi_cancel()

    @api.model
    def _cron_facturapi_fe_auto_send(self):
        companies = self.env["res.company"].search([
            ("connector_fe_enabled", "=", True),
            ("connector_fe_auto_send", "=", True),
        ])
        if not companies:
            return

        moves = self.search([
            ("company_id", "in", companies.ids),
            ("move_type", "in", ("out_invoice", "out_refund", "out_debit")),
            ("state", "=", "posted"),
            ("connector_facturapi_document_id", "=", False),
        ])

        for move in moves:
            try:
                move._connector_facturapi_post()
                _logger.info("Auto-send: submitted %s to DIAN", move.name)
            except Exception as e:
                _logger.error("Auto-send failed for %s: %s", move.name, e)

    def _dian_query(self, operation, document_key=None):
        self.ensure_one()
        doc = self.connector_facturapi_document_id
        if not doc:
            raise UserError(_("No DIAN document found for this invoice."))

        company = self.company_id
        if not company.facturapi_api_url or not company.facturapi_api_key:
            raise UserError(_("FacturAPI not configured for company %s") % company.name)

        # Get certificate from company
        certificate = company.certificate_id
        if not certificate:
            raise UserError(_("No certificate found for company %s") % company.name)
        if not certificate.is_valid:
            raise UserError(_("Certificate is not valid."))
        if not certificate.private_key_id:
            raise UserError(_("Certificate has no private key."))

        # Get PEM data
        def _to_str(value):
            if isinstance(value, bytes):
                decoded = value.decode("utf-8", errors="replace")
                if decoded.startswith("-----"):
                    return decoded
                try:
                    return base64.b64decode(decoded).decode("utf-8")
                except Exception:
                    return decoded
            return value or ""

        cert_pem = _to_str(certificate.pem_certificate)
        key_pem = _to_str(certificate.private_key_id.pem_key)

        base_url = doc._get_api_url()
        track_id = (
            document_key
            or self.connector_cufe
            or doc.cufe
            or doc.task_id
        )
        if not track_id:
            raise UserError(_("No document key or task ID available for DIAN query."))

        payload = {
            "track_id": track_id,
            "certificate_pem": cert_pem,
            "private_key_pem": key_pem,
            "environment": company.facturapi_environment or "produccion",
        }

        url = f"{base_url}/documents/dian/{operation}"
        response = requests.post(url, json=payload, headers=doc._get_headers(), timeout=30)
        response.raise_for_status()
        return response.json()

    def action_dian_get_status(self):
        for move in self:
            try:
                result = move._dian_query("get-status")
                status_info = result.get("result", {})
                doc = move.connector_facturapi_document_id
                if doc:
                    doc.write({
                        "dian_status": status_info.get("StatusCode", ""),
                        "dian_message": status_info.get("StatusMessage", status_info.get("StatusDescription", "")),
                        "error_message": status_info.get("ErrorMessage", ""),
                    })
                edi_doc = doc.edi_document_id if doc else move.edi_document_ids.filtered(
                    lambda d: d.edi_format_id.code == "facturapi_invoice" and d.state == "sent"
                )[:1]
                if edi_doc:
                    edi_doc.write({
                        "error": f"[DIAN GetStatus] {status_info.get('StatusDescription', '')} | {status_info.get('StatusMessage', '')}",
                        "blocking_level": "info" if status_info.get("IsValid") == "true" else "warning",
                    })
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "DIAN Status",
                        "message": status_info.get("StatusMessage", status_info.get("StatusDescription", str(status_info))),
                        "sticky": False,
                    },
                }
            except Exception as e:
                raise UserError(_("DIAN query failed: %s") % str(e))

    def action_dian_get_status_event(self):
        for move in self:
            try:
                result = move._dian_query("get-status-event")
                status_info = result.get("result", {})
                doc = move.connector_facturapi_document_id
                if doc:
                    doc.write({
                        "dian_status": status_info.get("StatusCode", doc.dian_status),
                        "dian_message": status_info.get("StatusMessage", status_info.get("StatusDescription", "")),
                    })
                edi_doc = doc.edi_document_id if doc else False
                if edi_doc:
                    edi_doc.write({
                        "error": f"[DIAN GetStatusEvent] {status_info.get('StatusDescription', '')}",
                        "blocking_level": "info" if status_info.get("IsValid") == "true" else "warning",
                    })
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "DIAN Event Status",
                        "message": status_info.get("StatusDescription", str(status_info)),
                        "sticky": False,
                    },
                }
            except Exception as e:
                raise UserError(_("DIAN query failed: %s") % str(e))

    def action_dian_get_xml(self):
        for move in self:
            try:
                result = move._dian_query("get-xml-by-document-key")
                xml_data = result.get("result", {})
                doc = move.connector_facturapi_document_id
                if doc and "xml_base64" in xml_data:
                    doc.write({
                        "application_response": base64.b64decode(xml_data["xml_base64"]).decode("utf-8", errors="replace"),
                    })
                edi_doc = doc.edi_document_id if doc else False
                if edi_doc:
                    edi_doc.write({
                        "error": f"[DIAN GetXml] {xml_data.get('XmlFileName', '')} - OK",
                        "blocking_level": "info",
                    })
                if "xml_base64" in xml_data:
                    xml_content = base64.b64decode(xml_data["xml_base64"])
                    attachment = self.env["ir.attachment"].create({
                        "name": f"{move.name}_dian_xml.zip",
                        "type": "binary",
                        "datas": base64.b64encode(xml_content),
                        "res_model": "account.move",
                        "res_id": move.id,
                    })
                    return {
                        "type": "ir.actions.act_window",
                        "res_model": "ir.attachment",
                        "res_id": attachment.id,
                        "view_mode": "form",
                        "target": "new",
                    }
                else:
                    return {
                        "type": "ir.actions.client",
                        "tag": "display_notification",
                        "params": {
                            "title": "DIAN XML",
                            "message": str(xml_data),
                            "sticky": False,
                        },
                    }
            except Exception as e:
                raise UserError(_("DIAN query failed: %s") % str(e))

    def action_dian_get_reference_notes(self):
        for move in self:
            try:
                result = move._dian_query("get-reference-notes")
                notes_data = result.get("result", {})
                edi_doc = move.connector_facturapi_document_id.edi_document_id if move.connector_facturapi_document_id else False
                if edi_doc:
                    edi_doc.write({
                        "error": f"[DIAN GetReferenceNotes] {notes_data.get('StatusDescription', str(notes_data))}",
                        "blocking_level": "info",
                    })
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "DIAN Reference Notes",
                        "message": notes_data.get("StatusDescription", str(notes_data)),
                        "sticky": False,
                    },
                }
            except Exception as e:
                raise UserError(_("DIAN query failed: %s") % str(e))
