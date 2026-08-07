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
        groups = self.env["account.tax.group"].search(
            [("dian_tax_type", "!=", False)]
        )
        for tax in self.search([]):
            if not tax.connector_dian_tax_type:
                continue
            group = next(
                (
                    g for g in groups
                    if g.dian_tax_type == tax.connector_dian_tax_type
                    and g.country_id.id == tax.country_id.id
                ),
                None,
            )
            if group and tax.tax_group_id != group:
                tax.tax_group_id = group
