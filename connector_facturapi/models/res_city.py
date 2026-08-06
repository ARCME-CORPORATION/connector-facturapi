from odoo import fields, models


class ResCity(models.Model):
    _inherit = "res.city"

    connector_dane_code = fields.Char(
        string="DANE Code",
        help="Numeric DANE code for DIAN electronic invoicing (e.g., 41573 for Pitalito)",
    )
