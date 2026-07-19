{
    "name": "FacturAPI - Colombia Electronic Invoice (FE)",
    "version": "0.1.0",
    "category": "Accounting/Localizations/EDI",
    "license": "LGPL-3",
    "summary": "Factura Electrónica de Venta for FacturAPI",
    "depends": [
        "connector_facturapi",
        "connector_facturapi_data",
        "account_move_name_sequence",
    ],
    "data": [
        "views/account_move_views.xml",
        "views/res_company_views.xml",
        "views/ir_sequence_date_range_views.xml",
        "data/resolution_data.xml",
        "data/ir_cron_data.xml",
        "report/factura_electronica_report.xml",
        "report/factura_electronica_template.xml",
    ],
    "installable": True,
    "auto_install": False,
}
