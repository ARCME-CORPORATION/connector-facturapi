import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AccountMoveSend(models.AbstractModel):
    _inherit = "account.move.send"

    @api.model
    def _get_all_extra_edis(self):
        result = super()._get_all_extra_edis()
        company = self.env.company
        if company.connector_fe_enabled:
            result["connector"] = {
                "label": _("DIAN (Colombia)"),
                "is_applicable": lambda move: move.move_type
                in ("out_invoice", "out_refund", "out_debit"),
                "help": _("Send electronic invoice to DIAN via FacturAPI"),
            }
        return result

    @api.model
    def _get_default_extra_edis(self, move):
        extra_edis = super()._get_default_extra_edis(move)
        if "connector" in extra_edis and move._connector_facturapi_is_sent():
            extra_edis.discard("connector")
        return extra_edis

    @api.model
    def _get_invoice_extra_attachments(self, move):
        result = super()._get_invoice_extra_attachments(move)
        dian_doc = move.connector_facturapi_document_id
        if not dian_doc:
            return result
        zip_attachment = dian_doc._get_dian_zip_attachment()
        if zip_attachment:
            return result + zip_attachment
        prefix = (
            "DS"
            if dian_doc.document_type in ("support_doc", "support_doc_credit_note")
            else "FE"
        )
        dian_xml = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", move.id),
                ("mimetype", "=", "application/xml"),
                ("name", "=like", f"{prefix}_%.xml"),
            ]
        )
        dian_pdf = self.env["ir.attachment"].search(
            [
                ("res_model", "=", "account.move"),
                ("res_id", "=", move.id),
                ("mimetype", "=", "application/pdf"),
                ("name", "=like", f"{prefix}_%.pdf"),
            ]
        )
        return result + dian_xml + dian_pdf

    def _prepare_invoice_proforma_pdf_report(self, invoice, invoice_data):
        if "connector" in invoice_data.get("extra_edis", set()):
            pdf_report = invoice_data["pdf_report"]
            content, report_type = (
                self.env["ir.actions.report"]
                .with_company(invoice.company_id)
                ._pre_render_qweb_pdf(
                    pdf_report.report_name,
                    invoice.ids,
                )
            )
            content_by_id = self.env["ir.actions.report"]._get_splitted_report(
                pdf_report.report_name, content, report_type
            )
            invoice_data["proforma_pdf_attachment_values"] = {
                "raw": content_by_id[invoice.id],
                "name": "%s_%s.pdf" % (invoice.name or "FE", invoice.id),
                "mimetype": "application/pdf",
                "res_model": invoice._name,
                "res_id": invoice.id,
            }
        else:
            super()._prepare_invoice_proforma_pdf_report(invoice, invoice_data)

    def _call_web_service_before_invoice_pdf_render(self, invoices_data):
        super()._call_web_service_before_invoice_pdf_render(invoices_data)
        for move, move_data in invoices_data.items():
            if "connector" in move_data.get("extra_edis", set()):
                if move._connector_facturapi_is_sent():
                    _logger.info(
                        "DIAN: skipping %s, already sent to DIAN", move.name
                    )
                    continue
                try:
                    move._connector_facturapi_post()
                    dian_doc = move.connector_facturapi_document_id
                    if not dian_doc:
                        raise ValueError("No DIAN document created")
                    state = dian_doc._wait_for_result(timeout=180, interval=5)
                    if state != "accepted":
                        error_msg = dian_doc.error_message or "DIAN did not accept the invoice"
                        raise UserError(
                            _("DIAN did not accept invoice %s (state: %s): %s")
                            % (move.name, state, error_msg)
                        )
                except Exception as e:
                    _logger.error("DIAN submission failed for %s: %s", move.name, e)
                    move_data["error"] = {
                        "error_title": _("DIAN Submission Failed"),
                        "errors": [str(e)],
                    }

    @api.model
    def _hook_if_success(self, moves_data):
        """Extends the core sending flow for the Colombian FE:

        * When an invoice is being submitted to DIAN in this flow ('connector'
          extra EDI), the email is deferred instead of being sent: the invoice
          stays 'not sent' so the email can be delivered once DIAN accepts it.
        * When sending emails for invoices that already have a DIAN document,
          invoices whose DIAN document is not 'accepted' are skipped.
        """
        to_send_mail = {}
        for move, move_data in moves_data.items():
            if "email" not in move_data.get("sending_methods", set()):
                continue
            if not self._is_applicable_to_move("email", move, **move_data):
                continue
            if "connector" in move_data.get("extra_edis", set()):
                move.is_move_sent = False
                _logger.info(
                    "DIAN: email for %s deferred until DIAN accepts it", move.name
                )
                continue
            dian_doc = move.connector_facturapi_document_id
            if dian_doc and dian_doc.state != "accepted":
                _logger.info(
                    "DIAN: skipping email for %s (DIAN state: %s)",
                    move.name,
                    dian_doc.state,
                )
                continue
            to_send_mail[move] = move_data
        if to_send_mail:
            self._send_mails(to_send_mail)
