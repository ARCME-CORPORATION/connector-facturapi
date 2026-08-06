from odoo import api, fields, models

DIAN_PAYMENT_FORMS = [
    ("1", "Contado"),
    ("2", "Crédito"),
]


class AccountPaymentTerm(models.Model):
    _inherit = "account.payment.term"

    connector_dian_payment_form_id = fields.Selection(
        DIAN_PAYMENT_FORMS,
        string="Forma de Pago DIAN",
        compute="_compute_connector_dian_payment_form_id",
        store=True,
        readonly=False,
        help="Forma de pago enviada a DIAN en el campo PaymentMeans/ID (1=Contado, "
        "2=Crédito). Se calcula según los días de la condición de pago: sin días "
        "vencibles → Contado; con días → Crédito. Se puede sobrescribir manualmente.",
    )

    @api.depends("line_ids.nb_days", "line_ids.delay_type")
    def _compute_connector_dian_payment_form_id(self):
        for term in self:
            has_days = any(line.nb_days for line in term.line_ids)
            has_deferral = any(
                line.delay_type != "days_after" for line in term.line_ids
            )
            term.connector_dian_payment_form_id = "2" if has_days or has_deferral else "1"
