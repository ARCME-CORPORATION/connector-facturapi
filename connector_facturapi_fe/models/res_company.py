import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..tools.api_client import FacturAPIClient

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    connector_fe_enabled = fields.Boolean(
        string="Facturación Electrónica",
        default=False,
    )
    connector_numbering_ranges = fields.Text(
        string="Rangos de Numeración",
        readonly=True,
    )

    def _get_api_client(self):
        self.ensure_one()
        api_key = self.facturapi_api_key
        if not api_key:
            raise UserError(_("Please configure the FacturAPI API Key."))
        company_id = self.facturapi_company_id
        if not company_id:
            raise UserError(_("Please configure the FacturAPI Company ID."))
        base_url = self.facturapi_api_url
        if not base_url:
            raise UserError(_("Please configure the FacturAPI API URL."))
        return FacturAPIClient(
            base_url=base_url, api_key=api_key, company_id=company_id
        )

    def _get_nit(self):
        self.ensure_one()
        vat = self.partner_id.vat or ""
        nit = vat.replace("-", "").replace(".", "").strip()
        if len(nit) > 9:
            nit = nit[:-1]
        return nit

    def action_UploadCertificate(self):
        self.ensure_one()
        certificate = self.certificate_id
        if not certificate:
            raise UserError(_("Please select a DIAN certificate first."))
        if not certificate.is_valid:
            raise UserError(_("The selected certificate is not valid."))
        if not certificate.private_key_id:
            raise UserError(_("The selected certificate has no private key."))

        client = self._get_api_client()
        result = client.upload_certificate(certificate, self.facturapi_company_id)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Certificado"),
                "message": result.get(
                    "message", "Certificado almacenado correctamente"
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def action_GetNumberingRange(self):
        self.ensure_one()
        certificate = self.certificate_id
        if not certificate:
            raise UserError(_("Please configure a DIAN certificate first."))

        software_code = self.connector_software_id
        if not software_code:
            raise UserError(_("Please configure the Software ID."))

        nit = self._get_nit()
        environment = self.connector_dian_environment or "produccion"
        client = self._get_api_client()
        result = client.get_numbering_range(nit, software_code, environment=environment)
        ranges = result.get("ranges", [])

        if ranges:
            lines = []
            for r in ranges:
                lines.append(
                    f"Resolución: {r.get('resolution', '')} | "
                    f"Fecha Res.: {r.get('resolution_date', '')} | "
                    f"Prefijo: {r.get('prefix', '')} | "
                    f"Desde: {r.get('number_from', '')} | "
                    f"Hasta: {r.get('number_to', '')} | "
                    f"Vigente: {r.get('valid_from', '')} al {r.get('valid_to', '')} | "
                    f"Key: {r.get('technical_key', '')}"
                )
            text = "\n".join(lines)
        else:
            text = ""

        self.sudo().write(
            {
                "connector_numbering_ranges": text,
            }
        )

        if ranges:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Rangos de Numeración"),
                    "message": _("Se encontraron %d rango(s).") % len(ranges),
                    "type": "success",
                    "sticky": False,
                },
            }
        return True
