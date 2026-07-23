from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    facturapi_api_url = fields.Char(
        related="company_id.facturapi_api_url",
        readonly=False,
    )
    facturapi_company_id = fields.Char(
        related="company_id.facturapi_company_id",
        readonly=False,
    )
    facturapi_api_key = fields.Char(
        related="company_id.facturapi_api_key",
        readonly=False,
    )
    facturapi_environment = fields.Selection(
        related="company_id.facturapi_environment",
        readonly=False,
    )
    certificate_id = fields.Many2one(
        related="company_id.certificate_id",
        readonly=False,
        domain=[("scope", "=", "facturapi"), ("is_valid", "=", True)],
        context={"default_scope": "facturapi"},
    )
    connector_software_id = fields.Char(
        related="company_id.connector_software_id",
        readonly=False,
    )
    connector_software_nit = fields.Char(
        related="company_id.connector_software_nit",
        readonly=False,
    )
    connector_software_pin = fields.Char(
        related="company_id.connector_software_pin",
        readonly=False,
    )
    connector_software_dv = fields.Char(
        related="company_id.connector_software_dv",
        readonly=False,
    )
    connector_test_set_id = fields.Char(
        related="company_id.connector_test_set_id",
        readonly=False,
    )
    connector_fe_auto_send = fields.Boolean(
        related="company_id.connector_fe_auto_send",
        readonly=False,
    )
