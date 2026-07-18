from odoo import api, fields, models


class L10nCoDianPaymentMethod(models.Model):
    _name = "l10n_co.dian.payment.method"
    _description = "DIAN Payment Method"
    _rec_name = "display_name"
    _order = "code"

    code = fields.Char(string="Code", required=True)
    name = fields.Char(string="Name", required=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"
