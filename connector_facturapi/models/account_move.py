from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_time = fields.Char(
        string="Invoice Time",
        size=20,
        help="Hora de emisión de la factura (HH:MM:SS)",
    )
    connector_resolution_number = fields.Char(
        string="Resolution Number",
    )
    connector_resolution_date = fields.Date(
        string="Resolution Date",
    )
    connector_resolution_date_from = fields.Date(
        string="Resolution Valid From",
    )
    connector_resolution_date_to = fields.Date(
        string="Resolution Valid To",
    )
    connector_resolution_number_from = fields.Integer(
        string="Resolution Number From",
    )
    connector_resolution_number_to = fields.Integer(
        string="Resolution Number To",
    )
    connector_authorization_prefix = fields.Char(
        string="Authorization Prefix",
        help="Ej: SETP, FELP, etc.",
    )
