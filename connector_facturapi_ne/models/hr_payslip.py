# Copyright 2026 Juan Arcos
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class HrPayslip(models.Model):
    _inherit = "hr.payslip"

    facturapi_ne_document_ids = fields.One2many(
        "facturapi.nomina.ne",
        "payslip_id",
        string="DIAN Nomina Documents",
    )
    facturapi_ne_document_id = fields.Many2one(
        "facturapi.nomina.ne",
        string="DIAN Nomina Document",
        compute="_compute_facturapi_ne_document",
    )
    connector_ne_state = fields.Selection(
        related="facturapi_ne_document_id.state",
        string="Nómina DIAN Status",
    )
    connector_ne_dian_status = fields.Char(
        related="facturapi_ne_document_id.dian_status",
        string="Nómina DIAN Code",
    )
    connector_ne_error = fields.Text(
        related="facturapi_ne_document_id.error_message",
        string="Nómina DIAN Error",
    )
    connector_ne_cune = fields.Char(
        related="facturapi_ne_document_id.cune",
        string="CUNE",
        readonly=True,
    )
    connector_ne_task_id = fields.Char(
        related="facturapi_ne_document_id.task_id",
        string="FacturAPI Task ID",
        readonly=True,
    )
    connector_ne_sequence_prefix = fields.Char(
        related="facturapi_ne_document_id.sequence_prefix",
        string="Prefijo",
        readonly=True,
    )
    connector_ne_sequence_number = fields.Integer(
        related="facturapi_ne_document_id.sequence_number",
        string="Consecutivo",
        readonly=True,
    )

    @api.depends("facturapi_ne_document_ids.state")
    def _compute_facturapi_ne_document(self):
        for slip in self:
            doc = self.env["facturapi.nomina.ne"].search(
                [("payslip_id", "=", slip.id)],
                order="id desc",
                limit=1,
            )
            slip.facturapi_ne_document_id = doc

    def _connector_facturapi_ne_post(self):
        self.ensure_one()
        if self.state != "done":
            raise UserError(
                _("La nómina debe estar confirmada antes de enviarla a la DIAN.")
            )
        existing = self.facturapi_ne_document_id
        if existing and existing.state not in ("to_send", "rejected"):
            raise UserError(_("Esta nómina ya fue enviada a la DIAN."))

        doc = self.env["facturapi.nomina.ne"].create(
            {
                "name": self.name or "/",
                "payslip_id": self.id,
                "company_id": self.company_id.id,
                "state": "to_send",
            }
        )
        self.facturapi_ne_document_id = doc
        doc._post_to_web_service()
        return True

    def action_facturapi_ne_send(self):
        for slip in self:
            slip._connector_facturapi_ne_post()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Nómina DIAN",
                "message": "Documento enviado al backend FacturAPI correctamente.",
                "sticky": False,
            },
        }

    def action_facturapi_ne_check_status(self):
        doc = self.facturapi_ne_document_id
        if doc:
            doc._check_task_status()
        status_msg = "Desconocido"
        if doc:
            status_msg = doc.dian_status or "Desconocido"
            if doc.dian_message:
                status_msg += f" - {doc.dian_message}"
            elif doc.error_message:
                status_msg += f" - {doc.error_message}"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Nómina DIAN",
                "message": status_msg,
                "sticky": False,
            },
        }
