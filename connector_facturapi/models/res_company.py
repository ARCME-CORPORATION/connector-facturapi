from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    facturapi_api_url = fields.Char(
        string="FacturAPI URL",
        default="http://host.docker.internal:8000",
        help="URL del backend FacturAPI",
    )
    facturapi_company_id = fields.Char(
        string="Company UUID",
        help="Identificador del tenant en FacturAPI (UUID)",
    )
    facturapi_api_key = fields.Char(
        string="FacturAPI API Key",
    )
    facturapi_environment = fields.Selection(
        [("habilitacion", "Habilitación"), ("produccion", "Producción")],
        string="FacturAPI Environment",
        default="habilitacion",
    )
    certificate_id = fields.Many2one(
        "certificate.certificate",
        string="DIAN Certificate",
        domain=[("scope", "=", "facturapi"), ("is_valid", "=", True)],
        help="Certificado digital para firma electrónica DIAN",
    )
    # Software identifiers (DIAN registration)
    connector_software_id = fields.Char(
        string="Software ID",
        help="Identificador del software asignado por DIAN",
    )
    connector_software_pin = fields.Char(
        string="Software PIN",
        help="PIN del software asignado por DIAN (se almacena cifrado)",
    )
    connector_software_dv = fields.Char(
        string="Software DV",
        size=5,
    )
    connector_test_set_id = fields.Char(
        string="Test Set ID",
        help="Identificador del set de pruebas en habilitación",
    )
    connector_tax_level_code = fields.Char(
        string="Tax Level Code",
        default="0",
        help="Código de nivel tributario (0=Gran Contribuyente, etc.)",
    )
    connector_fiscal_regime = fields.Char(
        string="Fiscal Regime Code",
        help="Código de régimen fiscal (R-99-PN para régimen común)",
    )
    connector_obligations = fields.Char(
        string="Tax Obligations",
        help="Códigos de obligaciones tributarias separados por coma",
    )
