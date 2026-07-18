import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    l10n_co_ds_document_id = fields.Many2one(
        "facturapi.document",
        string="DIAN DS Document",
        compute="_compute_l10n_co_ds_document",
        store=True,
    )
    l10n_co_ds_state = fields.Selection(
        related="l10n_co_ds_document_id.state",
        string="DIAN DS Status",
    )
    l10n_co_cuds = fields.Char(
        string="CUDS",
        size=96,
        readonly=True,
        copy=False,
    )
    l10n_co_ds_qr_code = fields.Text(
        string="DS QR Code",
        readonly=True,
        copy=False,
    )
    l10n_co_ds_xml_signed = fields.Text(
        string="DS XML Signed",
        readonly=True,
        copy=False,
    )
    l10n_co_ds_application_response = fields.Text(
        string="DS Application Response",
        readonly=True,
        copy=False,
    )
    l10n_co_ds_sequence_range_id = fields.Many2one(
        "ir.sequence.date_range",
        string="DIAN DS Sequence Range",
        readonly=True,
        copy=False,
    )

    @api.depends("edi_document_ids", "edi_document_ids.state")
    def _compute_l10n_co_ds_document(self):
        for move in self:
            doc = self.env["facturapi.document"].search(
                [
                    ("move_id", "=", move.id),
                    ("is_cancel", "=", False),
                    ("document_type", "in", ["support_doc", "support_doc_credit_note"]),
                ],
                limit=1,
            )
            move.l10n_co_ds_document_id = doc

    def _l10n_co_ds_post(self):
        self.ensure_one()
        if self.l10n_co_ds_document_id and self.l10n_co_ds_document_id.state != "to_send":
            raise UserError(_("This document has already been sent to DIAN."))

        edi_format = self.env["account.edi.format"].search([("code", "=", "facturapi_ds")], limit=1)
        if not edi_format:
            raise UserError(_("FacturAPI DS EDI format not found."))

        existing_edi_doc = self.edi_document_ids.filtered(
            lambda d: d.edi_format_id.code == "facturapi_ds" and d.state == "to_send"
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
                "document_type": edi_format._get_ds_document_type(self),
                "state": "to_send",
            }
        )
        facturapi_doc._post_to_web_service()
        return True

    def _l10n_co_ds_cancel(self):
        self.ensure_one()
        doc = self.l10n_co_ds_document_id
        if not doc or doc.state != "accepted":
            raise UserError(_("No accepted DIAN DS document to cancel."))

        cancel_doc = self.env["facturapi.document"].create(
            {
                "name": f"{self.name or '/'} (Cancel DS)",
                "move_id": self.id,
                "company_id": self.company_id.id,
                "document_type": doc.document_type,
                "is_cancel": True,
                "state": "to_send",
            }
        )
        cancel_doc._post_to_web_service()
        return True

    def _l10n_co_ds_check_status(self):
        self.ensure_one()
        doc = self.l10n_co_ds_document_id
        if doc:
            doc._check_task_status()

    def action_send_ds_to_dian(self):
        for move in self:
            move._l10n_co_ds_post()

    def action_check_ds_status(self):
        for move in self:
            move._l10n_co_ds_check_status()

    def action_cancel_ds(self):
        for move in self:
            move._l10n_co_ds_cancel()
