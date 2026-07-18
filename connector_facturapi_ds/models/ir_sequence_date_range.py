from odoo import fields, models


class IrSequenceDateRange(models.Model):
    _inherit = "ir.sequence.date_range"

    dian_ds_number_from = fields.Integer(
        string="DIAN DS Desde",
        help="Número inicial del rango de numeración DIAN DS",
    )
    dian_ds_number_to = fields.Integer(
        string="DIAN DS Hasta",
        help="Número final del rango de numeración DIAN DS",
    )
    dian_ds_resolution_number = fields.Char(
        string="Resolución DIAN DS",
        help="Número de resolución asignado por DIAN para Documento Soporte",
    )
    dian_ds_resolution_date = fields.Date(
        string="Fecha Resolución DS",
        help="Fecha de la resolución DIAN DS",
    )
    dian_ds_technical_key = fields.Char(
        string="Llave Técnica DS",
        help="Llave técnica (Technical Key) asignada por DIAN para DS",
    )
