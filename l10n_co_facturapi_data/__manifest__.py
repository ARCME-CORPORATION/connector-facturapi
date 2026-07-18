{
    "name": "FacturAPI - Colombia Data Master",
    "version": "0.1.0",
    "category": "Accounting/Localizations/EDI",
    "license": "LGPL-3",
    "summary": "DIAN master data for Colombian electronic invoicing",
    "depends": [
        "l10n_co_facturapi",
        "base_vat",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/l10n_co_dian_type_code.xml",
        "data/l10n_co_dian_tax_type.xml",
        "data/l10n_co_dian_uom.xml",
        "data/l10n_co_dian_payment_method.xml",
        "data/l10n_co_dian_responsibility.xml",
    ],
    "installable": True,
    "auto_install": False,
}
