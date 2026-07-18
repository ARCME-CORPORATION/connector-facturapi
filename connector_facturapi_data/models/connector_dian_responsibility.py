from odoo import api, fields, models


class L10nCoDianResponsibility(models.Model):
    _name = "connector.dian.responsibility"
    _description = "DIAN Fiscal Responsibility"
    _rec_name = "display_name"
    _order = "code"

    code = fields.Char(string="Code", required=True)
    name = fields.Char(string="Name", required=True)
    display_name = fields.Char(compute="_compute_display_name", store=True)
