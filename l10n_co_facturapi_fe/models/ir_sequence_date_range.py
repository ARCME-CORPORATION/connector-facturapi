from odoo import fields, models


class IrSequenceDateRange(models.Model):
    _inherit = "ir.sequence.date_range"

    dian_number_from = fields.Integer(
        string="DIAN Desde",
        help="Número inicial del rango de numeración DIAN",
    )
    dian_number_to = fields.Integer(
        string="DIAN Hasta",
        help="Número final del rango de numeración DIAN",
    )
    dian_resolution_number = fields.Char(
        string="Resolución DIAN",
        help="Número de resolución asignado por DIAN",
    )
    dian_resolution_date = fields.Date(
        string="Fecha Resolución",
        help="Fecha de la resolución DIAN",
    )
    dian_technical_key = fields.Char(
        string="Llave Técnica",
        help="Llave técnica (Technical Key) asignada por DIAN",
    )
