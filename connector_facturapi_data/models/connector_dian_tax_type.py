from odoo import api, fields, models


class L10nCoDianTaxType(models.Model):
    _name = "connector.dian.tax.type"
    _description = "DIAN Tax Type"
    _rec_name = "display_name"
    _order = "code"

    code = fields.Char(string="Code", required=True)
    name = fields.Char(string="Name", required=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
    active = fields.Boolean(default=True)

    @api.depends("code", "name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"[{rec.code}] {rec.name}"
