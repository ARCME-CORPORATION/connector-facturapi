from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    invoice_time = fields.Char(
        string="Invoice Time",
        size=20,
        help="Hora de emisión de la factura (HH:MM:SS)",
    )
    l10n_co_resolution_number = fields.Char(
        string="Resolution Number",
    )
    l10n_co_resolution_date = fields.Date(
        string="Resolution Date",
    )
    l10n_co_resolution_date_from = fields.Date(
        string="Resolution Valid From",
    )
    l10n_co_resolution_date_to = fields.Date(
        string="Resolution Valid To",
    )
    l10n_co_resolution_number_from = fields.Integer(
        string="Resolution Number From",
    )
    l10n_co_resolution_number_to = fields.Integer(
        string="Resolution Number To",
    )
    l10n_co_authorization_prefix = fields.Char(
        string="Authorization Prefix",
        help="Ej: SETP, FELP, etc.",
    )
