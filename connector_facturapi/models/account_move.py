import logging

from lxml import etree

from odoo import api, models

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

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
