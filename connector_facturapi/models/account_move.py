import base64
import logging

from lxml import etree

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

DIAN_NAMESPACES = {
    'inv': 'urn:oasis:names:specification:ubl:schema:xsd:Invoice-2',
    'cn': 'urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2',
    'ad': 'urn:oasis:names:specification:ubl:schema:xsd:AttachedDocument-2',
    'cac': 'urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2',
    'cbc': 'urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2',
}


class AccountMove(models.Model):
    _inherit = 'account.move'

    connector_import_cufe = fields.Char(
        string="CUFE a Importar",
        copy=False,
        help="Pegue el CUFE de la factura electrónica del proveedor y presione "
             "'Importar por CUFE'. Odoo consultará el XML firmado en la DIAN y "
             "llenará automáticamente los campos de esta factura.",
    )

    @api.model
    def _get_ubl_cii_builder_from_xml_tree(self, tree):
        # EXTENDS account_edi_ubl_cii
        # Detect DIAN electronic invoicing documents.
        # DIAN uses CustomizationID "10" and UBLVersionID "UBL 2.1"
        # which don't match the standard UBL checks.
        customization_id = tree.findtext('{*}CustomizationID') or ''
        profile_id = tree.findtext('{*}ProfileID') or ''
        ubl_version = tree.findtext('{*}UBLVersionID') or ''

        if 'DIAN' in profile_id or (customization_id == '10' and 'UBL' in ubl_version):
            return self.env['account.edi.xml.ubl_21']

        return super()._get_ubl_cii_builder_from_xml_tree(tree)

    def _message_post_after_hook(self, new_message, message_values):
        res = super()._message_post_after_hook(new_message, message_values)
        if self._context.get('from_alias') and new_message.attachment_ids:
            _logger.info(
                "FacturAPI connector: email with attachments %s posted on move %s",
                [a.name for a in new_message.attachment_ids], self.id,
            )
        return res

    def _connector_import_get_api_url(self):
        self.ensure_one()
        company = self.company_id or self.env.company
        url = company.facturapi_api_url
        if not url:
            raise UserError(
                _("FacturAPI URL no configurada para la empresa %s.") % company.name
            )
        return url.rstrip('/') + '/api/v1'

    def _connector_import_fetch_xml(self, cufe, environment):
        """Call the FacturAPI backend (GetXmlByDocumentKey) for one environment.

        :returns: the parsed "result" dict from the API response.
        """
        company = self.company_id or self.env.company
        payload = {"track_id": cufe, "environment": environment}
        token = f"{company.facturapi_company_id}:{company.facturapi_api_key}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{self._connector_import_get_api_url()}/documents/dian/get-xml-by-document-key"

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            return response.json().get("result") or {}
        except requests.exceptions.RequestException as e:
            raise UserError(_("Error consultando el backend FacturAPI: %s") % e)

    def action_connector_import_by_cufe(self):
        """Fetch the signed XML from DIAN by CUFE and fill this vendor bill.

        Flow:
        1. POST /documents/dian/get-xml-by-document-key on the FacturAPI backend
           (SOAP GetXmlByDocumentKey with the company certificate), trying the
           company environment first and the other one as fallback.
        2. Store the returned ZIP (base64) as an ir.attachment on the move.
        3. Let the native EDI pipeline (_extend_with_attachments) unwrap the
           ZIP, detect the DIAN UBL 2.1 XML and fill partner, lines and taxes.
        """
        self.ensure_one()
        cufe = (self.connector_import_cufe or '').strip()
        if not cufe:
            raise UserError(_("Ingrese el CUFE de la factura electrónica."))
        if self.move_type not in ('in_invoice', 'in_refund'):
            raise UserError(_(
                "La importación por CUFE solo aplica a facturas de proveedor."
            ))
        if self.state != 'draft':
            raise UserError(_("La factura debe estar en borrador."))

        company = self.company_id or self.env.company
        if not company.facturapi_company_id or not company.facturapi_api_key:
            raise UserError(
                _("FacturAPI Company ID / API Key no configurados para la empresa %s.")
                % company.name
            )

        # Vendor bills are usually production documents even while the company
        # is still sending its own invoices in habilitacion: try both.
        company_env = company.connector_dian_environment or 'produccion'
        environments = [company_env] + [
            e for e in ('produccion', 'habilitacion') if e != company_env
        ]

        result = {}
        for environment in environments:
            result = self._connector_import_fetch_xml(cufe, environment)
            if result.get("xml_base64"):
                break

        xml_b64 = result.get("xml_base64")
        if not xml_b64:
            detail = ", ".join(
                f"{k}: {v}" for k, v in result.items() if isinstance(v, str)
            )
            raise UserError(_(
                "La DIAN no devolvió XML para este CUFE.\n%s" % (detail or "Sin detalle."),
            ))

        # DIAN may return the plain signed XML or a ZIP package depending on
        # the service version; store it in the right format so the EDI
        # decoders can process it.
        content = base64.b64decode(xml_b64)
        if content.lstrip()[:5] == b'<?xml' or content.lstrip()[:1] == b'<':
            attachment = self.env['ir.attachment'].create({
                'name': f"DIAN_{cufe[:32]}.xml",
                'datas': xml_b64,
                'mimetype': 'application/xml',
                'res_model': self._name,
                'res_id': self.id,
            })
        else:
            attachment = self.env['ir.attachment'].create({
                'name': f"DIAN_{cufe[:32]}.zip",
                'datas': xml_b64,
                'mimetype': 'application/zip',
                'res_model': self._name,
                'res_id': self.id,
            })

        imported = self._extend_with_attachments(attachment, new=False)

        if not self.invoice_line_ids:
            raise UserError(_(
                "Se obtuvo el XML de la DIAN pero no se pudo importar como "
                "factura (verifique que el documento sea una factura "
                "electrónica válida y que su empresa figure como adquiriente)."
            ))

        _logger.info(
            "FacturAPI connector: CUFE %s imported into move %s (native=%s)",
            cufe, self.name, bool(imported),
        )

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Importación por CUFE"),
                'message': _("Factura actualizada con la información de la DIAN."),
                'type': 'success',
                'sticky': False,
            },
        }
