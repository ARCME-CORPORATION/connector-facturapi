from odoo import api, models


class AccountEdiFormat(models.Model):
    _inherit = "account.edi.format"

    @api.model
    def _connector_facturapi_is_invoice_type(self, move):
        return move.move_type in ("out_invoice", "out_refund", "out_debit_note")
