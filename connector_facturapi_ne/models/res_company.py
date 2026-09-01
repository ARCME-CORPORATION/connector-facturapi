# Copyright 2026 Juan Arcos
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResCompany(models.Model):
    _inherit = "res.company"

    connector_ne_enabled = fields.Boolean(
        string="Nómina Electrónica DIAN",
        help="Habilita el envío de nómina electrónica a la DIAN vía FacturAPI",
    )
    connector_ne_auto_send = fields.Boolean(
        string="Auto Send Nómina",
        help="Enviar nóminas automáticamente a la DIAN al confirmarlas",
    )
    connector_ne_prefix = fields.Char(
        string="Prefijo Nómina",
        default="NP",
        help="Prefijo para la numeración de la nómina electrónica",
    )
