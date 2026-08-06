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
    connector_dian_status_code = fields.Char(
        related="connector_facturapi_document_id.dian_status",
        string="DIAN Status Code",
    )
    connector_dian_error = fields.Text(
        related="connector_facturapi_document_id.error_message",
        string="DIAN Error",
    )
    connector_dian_error_details = fields.Text(
        related="connector_facturapi_document_id.dian_error_details",
        string="DIAN Error Details",
    )
    connector_dian_task_id = fields.Char(
        related="connector_facturapi_document_id.task_id",
        string="DIAN Task ID",
    )
    connector_dian_accepted_datetime = fields.Datetime(
        related="connector_facturapi_document_id.connector_dian_accepted_datetime",
        string="DIAN Accepted At",
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
    connector_dian_invoice_type_code = fields.Selection(
        [
            ("01", "Factura de Venta"),
            ("02", "Factura de Exportación"),
            ("03", "Instrumento electrónico de transmisión"),
            ("04", "Factura de Venta tipo 04"),
        ],
        string="Tipo de Factura DIAN",
        default="01",
        copy=True,
    )

    @api.depends(
        "restrict_mode_hash_table",
        "state",
        "inalterable_hash",
        "connector_facturapi_document_id.state",
    )
    def _compute_show_reset_to_draft_button(self):
        for move in self:
            show = (
                not self._is_move_restricted(move)
                and not move.inalterable_hash
                and (
                    move.state == "cancel"
                    or (move.state == "posted" and not move.need_cancel_request)
                )
            )
            move.show_reset_to_draft_button = (
                show and move.connector_facturapi_document_id.state != "accepted"
            )


    def _compute_connector_facturapi_document(self):
        for move in self:
            doc = self.env["facturapi.document"].search(
                [
                    ("move_id", "=", move.id),
                    ("is_cancel", "=", False),
                ],
                order="id desc",
                limit=1,
            )
            move.connector_facturapi_document_id = doc

    def _connector_facturapi_post(self):
        self.ensure_one()
        existing = self.connector_facturapi_document_id
        if existing and existing.state not in ("to_send", "rejected"):
            raise UserError(_("This invoice has already been sent to DIAN."))

        facturapi_doc = self.env["facturapi.document"].create(
            {
                "name": self.name or "/",
                "move_id": self.id,
                "company_id": self.company_id.id,
                "state": "to_send",
            }
        )
        self.connector_facturapi_document_id = facturapi_doc
        facturapi_doc._post_to_web_service()
        return True

    def _connector_facturapi_is_sent(self):
        self.ensure_one()
        doc = self.connector_facturapi_document_id
        return bool(doc and doc.state != "rejected")

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
        return True

    def action_resend_to_dian(self):
        for move in self:
            doc = move.connector_facturapi_document_id
            if doc and doc.state != "rejected":
                raise UserError(_("Only rejected documents can be resent to DIAN."))
            move._connector_facturapi_post()
        return True

    def action_check_dian_status(self):
        for move in self:
            move._connector_facturapi_check_status()
        doc = self.connector_facturapi_document_id
        status_msg = doc.dian_status or "Unknown"
        if doc.dian_message:
            status_msg += f" - {doc.dian_message}"
        elif doc.error_message:
            status_msg += f" - {doc.error_message}"
        return True

    def action_cancel_dian(self):
        for move in self:
            move._connector_facturapi_cancel()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "DIAN",
                "message": "Anulación enviada a DIAN correctamente.",
                "sticky": False,
            },
        }

    @api.model
    def _cron_facturapi_fe_auto_send(self):
        companies = self.env["res.company"].search(
            [
                ("connector_fe_enabled", "=", True),
                ("connector_fe_auto_send", "=", True),
            ]
        )
        if not companies:
            return

        moves = self.search(
            [
                ("company_id", "in", companies.ids),
                ("move_type", "in", ("out_invoice", "out_refund", "out_debit")),
                ("state", "=", "posted"),
                ("connector_facturapi_document_id", "=", False),
            ]
        )

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
        if not company.facturapi_company_id:
            raise UserError(
                _("FacturAPI Company ID not configured for company %s") % company.name
            )

        base_url = doc._get_api_url()
        track_id = document_key or self.connector_cufe or doc.cufe or doc.task_id
        if not track_id:
            raise UserError(_("No document key or task ID available for DIAN query."))

        token = f"{company.facturapi_company_id}:{company.facturapi_api_key}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        payload = {
            "track_id": track_id,
            "environment": company.connector_dian_environment or "produccion",
        }

        url = f"{base_url}/documents/dian/{operation}"
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def action_dian_get_status(self):
        for move in self:
            try:
                result = move._dian_query("get-status")
                status_info = result.get("result", {})
                doc = move.connector_facturapi_document_id
                if doc:
                    doc.write(
                        {
                            "dian_status": status_info.get("StatusCode", ""),
                            "dian_message": status_info.get(
                                "StatusMessage",
                                status_info.get("StatusDescription", ""),
                            ),
                            "error_message": status_info.get("ErrorMessage", ""),
                        }
                    )
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "DIAN Status",
                        "message": status_info.get(
                            "StatusMessage",
                            status_info.get("StatusDescription", str(status_info)),
                        ),
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
                    doc.write(
                        {
                            "dian_status": status_info.get(
                                "StatusCode", doc.dian_status
                            ),
                            "dian_message": status_info.get(
                                "StatusMessage",
                                status_info.get("StatusDescription", ""),
                            ),
                        }
                    )
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": "DIAN Event Status",
                        "message": status_info.get(
                            "StatusDescription", str(status_info)
                        ),
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
                    doc.write(
                        {
                            "application_response": base64.b64decode(
                                xml_data["xml_base64"]
                            ).decode("utf-8", errors="replace"),
                        }
                    )
                if "xml_base64" in xml_data:
                    xml_content = base64.b64decode(xml_data["xml_base64"])
                    attachment = self.env["ir.attachment"].create(
                        {
                            "name": f"{move.name}_dian_xml.zip",
                            "type": "binary",
                            "datas": base64.b64encode(xml_content),
                            "res_model": "account.move",
                            "res_id": move.id,
                        }
                    )
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
