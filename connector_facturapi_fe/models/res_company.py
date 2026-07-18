import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from ..tools.api_client import FacturAPIClient

_logger = logging.getLogger(__name__)

API_BASE_URL = "http://host.docker.internal:8000"


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
    connector_dian_environment = fields.Selection(
        selection=[
            ("produccion", "Producción"),
            ("habilitacion", "Habilitación (Pruebas)"),
        ],
        string="Ambiente DIAN",
        default="produccion",
    )

    def _get_api_client(self):
        self.ensure_one()
        api_key = self.facturapi_api_key
        if not api_key:
            raise UserError(_("Please configure the FacturAPI API Key."))
        return FacturAPIClient(base_url=API_BASE_URL, api_key=api_key)

    def _get_nit(self):
        self.ensure_one()
        vat = self.partner_id.vat or ""
        nit = vat.replace("-", "").replace(".", "").strip()
        if len(nit) > 9:
            nit = nit[:-1]
        return nit

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
        result = client.get_numbering_range(nit, software_code, certificate, environment=environment)
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

        self.sudo().write({
            "connector_numbering_ranges": text,
        })

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
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Sin resultados"),
                "message": _("No se encontraron rangos de numeración."),
                "type": "warning",
                "sticky": False,
            },
        }
