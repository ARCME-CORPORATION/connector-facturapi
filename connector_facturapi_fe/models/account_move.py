import logging

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
        size=96,
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
