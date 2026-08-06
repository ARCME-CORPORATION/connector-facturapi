from odoo import models, fields


WITHHOLDING_CODES = {"05", "06", "07", "08"}

DIAN_TAX_TYPES = [
    ("01", "IVA"),
    ("02", "IC"),
    ("03", "ICA"),
    ("04", "INC"),
    ("05", "ReteIVA"),
    ("06", "ReteFuente"),
    ("07", "ReteICA"),
    ("08", "ReteCREE"),
]


class AccountTaxGroup(models.Model):
    _inherit = "account.tax.group"

    dian_tax_type = fields.Selection(
        DIAN_TAX_TYPES,
        string="Tipo de impuesto DIAN",
        index=True,
    )


class AccountTax(models.Model):
    _inherit = "account.tax"

    connector_dian_tax_type = fields.Selection(
        DIAN_TAX_TYPES,
        string="Tipo de impuesto DIAN",
        default="01",
    )

    def _connector_assign_dian_tax_groups(self):
        groups_by_type = {
            group.dian_tax_type: group
            for group in self.env["account.tax.group"].search(
                [("dian_tax_type", "!=", False)]
            )
        }
        for tax in self.search([]):
            group = groups_by_type.get(tax.connector_dian_tax_type)
            if group and tax.tax_group_id != group:
                tax.tax_group_id = group
