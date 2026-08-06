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
    connector_dian_environment = fields.Selection(
        [("habilitacion", "Habilitación (Pruebas)"), ("produccion", "Producción")],
        string="Ambiente DIAN",
        default="habilitacion",
    )
    certificate_id = fields.Many2one(
        "certificate.certificate",
        string="DIAN Certificate",
        domain=[("scope", "=", "facturapi"), ("is_valid", "=", True)],
        context={"default_scope": "facturapi"},
        help="Certificado digital para firma electrónica DIAN",
    )
    connector_software_id = fields.Char(
        string="Software ID",
        help="Identificador del software asignado por DIAN",
    )
    connector_software_pin = fields.Char(
        string="Software PIN",
        help="PIN del software asignado por DIAN (se almacena cifrado)",
    )
    connector_test_set_id = fields.Char(
        string="Test Set ID",
        help="Identificador del set de pruebas en habilitación",
    )
    connector_fe_auto_send = fields.Boolean(
        string="Auto Send FE",
        help="Enviar facturas electrónicas automáticamente",
    )
