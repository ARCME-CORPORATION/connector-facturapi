# Copyright 2026 Juan Arcos
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class HrPayslipRun(models.Model):
    _inherit = "hr.payslip.run"

    facturapi_ne_state = fields.Selection(
        [
            ("not_sent", "Sin enviar"),
            ("to_send", "Pendiente"),
            ("processing", "Procesando"),
            ("accepted", "Aceptada"),
            ("rejected", "Rechazada"),
            ("partial", "Parcial"),
        ],
        string="Nómina DIAN",
        compute="_compute_facturapi_ne_state",
    )

    @api.depends(
        "slip_ids", "slip_ids.connector_ne_state"
    )
    def _compute_facturapi_ne_state(self):
        for run in self:
            slip_states = run.slip_ids.mapped("connector_ne_state")
            if not slip_states:
                run.facturapi_ne_state = "not_sent"
            elif all(s == "accepted" for s in slip_states) and slip_states:
                run.facturapi_ne_state = "accepted"
            elif any(s == "rejected" for s in slip_states):
                run.facturapi_ne_state = "rejected"
            elif all(s == "processing" for s in slip_states) and len(slip_states) == len(
                run.slip_ids
            ):
                run.facturapi_ne_state = "processing"
            elif any(s in ("to_send", "processing") for s in slip_states):
                run.facturapi_ne_state = "partial"
            elif slip_states and all(s == "to_send" for s in slip_states):
                run.facturapi_ne_state = "to_send"
            else:
                run.facturapi_ne_state = "not_sent"

    def action_facturapi_ne_send_all(self):
        if self.state != "done":
            raise UserError(
                _("El lote de nómina debe estar confirmado para enviarlo a la DIAN.")
            )
        sent = 0
        skipped = 0
        for slip in self.slip_ids:
            try:
                if slip.facturapi_ne_document_id and slip.facturapi_ne_document_id.state not in (
                    "to_send", "rejected"
                ):
                    skipped += 1
                    continue
                slip._connector_facturapi_ne_post()
                sent += 1
            except Exception as e:
                _logger.error(
                    "FacturAPI NE failed for payslip %s: %s", slip.name, e
                )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Nómina DIAN",
                "message": f"{sent} nómina(s) enviada(s), {skipped} omitida(s).",
                "sticky": False,
            },
        }

    def action_facturapi_ne_check_all(self):
        for slip in self.slip_ids:
            doc = slip.facturapi_ne_document_id
            if doc and doc.state in ("processing", "to_send"):
                try:
                    doc._check_task_status()
                except Exception as e:
                    _logger.error(
                        "FacturAPI NE check failed for %s: %s", slip.name, e
                    )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Nómina DIAN",
                "message": "Estados consultados.",
                "sticky": False,
            },
        }
