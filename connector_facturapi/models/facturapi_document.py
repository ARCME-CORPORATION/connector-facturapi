import json
import logging

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FacturapiDocument(models.Model):
    _name = "facturapi.document"
    _description = "FacturAPI DIAN Document"
    _rec_name = "name"
    _order = "create_date desc"

    name = fields.Char(string="Document Reference", readonly=True)
    move_id = fields.Many2one("account.move", string="Invoice", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", string="Company", required=True)
    edi_document_id = fields.Many2one("account.edi.document", string="EDI Document")

    state = fields.Selection(
        [
            ("to_send", "To Send"),
            ("processing", "Processing"),
            ("accepted", "Accepted"),
            ("rejected", "Rejected"),
        ],
        string="Status",
        default="to_send",
        required=True,
        copy=False,
    )
    is_cancel = fields.Boolean(string="Cancel Document", default=False, copy=False)

    task_id = fields.Char(string="FacturAPI Task ID", index=True, copy=False)
    document_type = fields.Selection(
        [
            ("invoice", "Factura Electronica de Venta"),
            ("credit_note", "Nota Credito"),
            ("debit_note", "Nota Debito"),
        ],
        string="Document Type",
    )

    cufe = fields.Char(string="CUFE/CUDE", copy=False)
    qr_code = fields.Text(string="QR Code (Base64)", copy=False)
    xml_signed = fields.Text(string="Signed XML", copy=False)
    application_response = fields.Text(string="Application Response", copy=False)
    attached_document = fields.Text(string="Attached Document", copy=False)

    dian_status = fields.Char(string="DIAN Status Code", copy=False)
    dian_message = fields.Text(string="DIAN Status Message", copy=False)
    error_message = fields.Text(string="Error Message", copy=False)

    def _get_api_url(self):
        url = self.company_id.facturapi_api_url
        if not url:
            raise UserError(_("FacturAPI URL not configured for company %s") % self.company_id.name)
        return url.rstrip("/") + "/api/v1"

    def _get_headers(self):
        return {
            "Authorization": f"Bearer {self.company_id.facturapi_api_key}",
            "Content-Type": "application/json",
        }

    def _post_to_web_service(self):
        self.ensure_one()
        move = self.move_id
        is_ds = self.document_type in ("support_doc", "support_doc_credit_note")

        if is_ds:
            edi_format = self.env["account.edi.format"].search([("code", "=", "facturapi_ds")], limit=1)
            if not edi_format:
                raise UserError(_("FacturAPI DS EDI format not found. Please check module installation."))
            payload = edi_format._build_facturapi_ds_payload(move)
        else:
            edi_format = self.env["account.edi.format"].search([("code", "=", "facturapi_invoice")], limit=1)
            if not edi_format:
                raise UserError(_("FacturAPI EDI format not found. Please check module installation."))
            payload = edi_format._build_facturapi_payload(move)

        base_url = self._get_api_url()
        url = f"{base_url}/documents/submit"
        response = requests.post(url, json=payload, headers=self._get_headers(), timeout=120)
        response.raise_for_status()
        result = response.json()

        self.write({
            "task_id": result.get("task_id"),
            "state": "processing",
        })
        _logger.info("FacturAPI task created: %s for invoice %s", result.get("task_id"), move.name)

    def _check_task_status(self):
        self.ensure_one()
        if not self.task_id:
            return

        base_url = self._get_api_url()
        url = f"{base_url}/documents/{self.task_id}/status"

        response = requests.get(url, headers=self._get_headers(), timeout=120)
        response.raise_for_status()
        data = response.json()

        api_status = data.get("status", "")
        if api_status == "completed":
            self._fetch_and_process_result()
        elif api_status == "failed":
            self.write({
                "state": "rejected",
                "error_message": data.get("error_message", "Processing failed"),
            })
            if self.edi_document_id:
                self.edi_document_id.write({
                    "error": data.get("error_message", "Processing failed"),
                    "blocking_level": "error",
                })

    def _fetch_and_process_result(self):
        self.ensure_one()

        base_url = self._get_api_url()
        url = f"{base_url}/documents/{self.task_id}/result"

        response = requests.get(url, headers=self._get_headers(), timeout=120)
        response.raise_for_status()
        data = response.json()

        write_vals = {
            "state": "accepted",
            "cufe": data.get("cufe_cude", ""),
            "qr_code": data.get("qr_code", ""),
            "xml_signed": data.get("xml_signed", ""),
            "application_response": data.get("application_response", ""),
            "dian_status": data.get("dian_status", ""),
            "error_message": False,
        }
        self.write(write_vals)

        move = self.move_id
        is_ds = self.document_type in ("support_doc", "support_doc_credit_note")

        if is_ds:
            move.write({
                "connector_cuds": data.get("cufe_cude", ""),
                "connector_ds_qr_code": data.get("qr_code", ""),
                "connector_ds_xml_signed": data.get("xml_signed", ""),
                "connector_ds_application_response": data.get("application_response", ""),
            })
        else:
            move.write({
                "connector_cufe": data.get("cufe_cude", ""),
                "connector_qr_code": data.get("qr_code", ""),
                "connector_xml_signed": data.get("xml_signed", ""),
                "connector_application_response": data.get("application_response", ""),
            })

        if self.edi_document_id:
            self.edi_document_id.write({
                "state": "sent",
                "error": False,
                "blocking_level": False,
            })

        _logger.info("DIAN accepted: task=%s cufe=%s", self.task_id, data.get("cufe_cude", "")[:16])

    @api.model
    def _cron_check_dian_status(self):
        processing = self.search([("state", "=", "processing")])
        for doc in processing:
            try:
                doc._check_task_status()
            except Exception as e:
                _logger.error("Failed to check DIAN status for %s: %s", doc.name, e)
                doc.write({"error_message": str(e)[:2000]})

    def action_check_status(self):
        self.ensure_one()
        self._check_task_status()

    def action_fetch_result(self):
        self.ensure_one()
        if self.state == "processing" and self.task_id:
            self._fetch_and_process_result()

    def action_retry(self):
        self.ensure_one()
        self.write({"state": "to_send", "error_message": False, "task_id": False})
        self._post_to_web_service()
