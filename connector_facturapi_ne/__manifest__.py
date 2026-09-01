{
    "name": "FacturAPI - Colombia Nomina Electronica (NE)",
    "version": "0.2.0",
    "category": "Accounting/Localizations/EDI",
    "license": "LGPL-3",
    "summary": "Documento Soporte de Pago de Nomina Electronica DIAN via FacturAPI",
    "depends": [
        "connector_facturapi",
        "payroll",
        "hr_contract",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/hr_payslip_views.xml",
        "views/hr_payslip_run_views.xml",
        "views/res_company_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
