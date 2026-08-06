from odoo import fields, models


class ResCountryState(models.Model):
    _inherit = "res.country.state"

    connector_dane_code = fields.Char(
        string="DANE Code",
        help="Numeric DANE code for DIAN electronic invoicing (e.g., 11 for Bogotá D.C.)",
    )
