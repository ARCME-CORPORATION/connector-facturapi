from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    connector_dian_fiscal_regime = fields.Selection(
        selection=[
            ("R-99-PN", "R-99-PN - Régimen Simple"),
            ("O-15", "O-15 - Gran Contribuyente"),
            ("O-23", "O-23 - Autorretenedor"),
            ("O-47", "O-47 - Régimen Común"),
            ("O-48", "O-48 - Entidades sin ánimo de lucro"),
            ("O-49", "O-49 - Zona Franca"),
            ("O-99", "O-99 - No Aplica"),
        ],
        string="Régimen Fiscal DIAN",
        help="Código de régimen fiscal según tabla de DIAN",
        default="R-99-PN",
    )
    connector_dian_tax_responsibility = fields.Selection(
        selection=[
            ("01", "01 - IVA (Impuesto sobre las Ventas)"),
            ("02", "02 - INC (Impuesto Nacional al Consumo)"),
            ("03", "03 - ICA (Impuesto de Industria y Comercio)"),
            ("04", "04 - INPO (Impuesto a los Productos)"),
        ],
        string="Responsabilidad Tributaria DIAN",
        help="Código de responsabilidad tributaria según tabla de DIAN",
        default="01",
    )
