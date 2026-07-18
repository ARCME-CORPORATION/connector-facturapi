import logging

from odoo import _, api, models

_logger = logging.getLogger(__name__)


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_all_extra_edis(self):
        result = super()._get_all_extra_edis()
        company = self.env.company
        if company.l10n_co_ds_enabled:
            result["l10n_co_ds"] = {
                "label": _("DIAN DS (Colombia)"),
                "is_applicable": lambda move: move.move_type in ("out_invoice", "out_refund"),
                "help": _("Send Documento Soporte to DIAN via FacturAPI"),
            }
        return result

    def _call_web_service_before_invoice_pdf_render(self, invoices_data):
        super()._call_web_service_before_invoice_pdf_render(invoices_data)
        for move, move_data in invoices_data.items():
            if "l10n_co_ds" in move_data.get("extra_edis", set()):
                try:
                    move._l10n_co_ds_post()
                except Exception as e:
                    _logger.error("DIAN DS submission failed for %s: %s", move.name, e)
                    move_data["error"] = {
                        "error_title": _("DIAN DS Submission Failed"),
                        "errors": [str(e)],
                    }
