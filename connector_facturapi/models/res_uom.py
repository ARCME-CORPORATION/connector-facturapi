from odoo import models, fields


class UomUom(models.Model):
    _inherit = "uom.uom"

    connector_dian_unit_code = fields.Char(
        string="Código DIAN Unidad",
        help="Código de unidad de medida según tabla DIAN (94, EA, KGM, LTR, ZZ, etc.)",
    )
