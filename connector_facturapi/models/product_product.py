from odoo import models, fields


class ProductProduct(models.Model):
    _inherit = "product.product"

    connector_unspsc_code = fields.Char(
        string="Código UNSPSC",
        help="Código UNSPSC del producto (estándar de clasificación de productos)",
    )
