{
    "name": "FacturAPI - Colombia Documento Soporte (DS)",
    "version": "0.1.0",
    "category": "Accounting/Localizations/EDI",
    "license": "LGPL-3",
    "summary": "Documento Soporte en adquisiciones a no obligados a facturar para FacturAPI",
    "depends": [
        "connector_facturapi",
        "connector_facturapi_data",
        "connector_facturapi_fe",
    ],
    "data": [
        "data/edi_format_data.xml",
        "views/account_move_views.xml",
        "views/res_company_views.xml",
        "views/ir_sequence_date_range_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
