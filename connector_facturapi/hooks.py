TAX_TYPE_MAP = {
    "l10n_co_tax_0": "01",
    "l10n_co_tax_1": "01",
    "l10n_co_tax_2": "01",
    "l10n_co_tax_4": "01",
    "l10n_co_tax_5": "01",
    "l10n_co_tax_6": "01",
    "l10n_co_tax_7": "01",
    "l10n_co_tax_8": "01",
    "l10n_co_tax_9": "01",
    "l10n_co_tax_10": "01",
    "l10n_co_tax_11": "01",
    "l10n_co_tax_12": "05",
    "l10n_co_tax_13": "05",
    "l10n_co_tax_14": "05",
    "l10n_co_tax_15": "05",
    "l10n_co_tax_16": "06",
    "l10n_co_tax_17": "06",
    "l10n_co_tax_18": "06",
    "l10n_co_tax_19": "06",
    "l10n_co_tax_20": "06",
    "l10n_co_tax_21": "06",
    "l10n_co_tax_22": "06",
    "l10n_co_tax_23": "06",
    "l10n_co_tax_24": "06",
    "l10n_co_tax_25": "06",
    "l10n_co_tax_26": "06",
    "l10n_co_tax_27": "06",
    "l10n_co_tax_28": "06",
    "l10n_co_tax_29": "06",
    "l10n_co_tax_30": "06",
    "l10n_co_tax_31": "06",
    "l10n_co_tax_32": "06",
    "l10n_co_tax_33": "06",
    "l10n_co_tax_34": "06",
    "l10n_co_tax_35": "06",
    "l10n_co_tax_36": "06",
    "l10n_co_tax_37": "06",
    "l10n_co_tax_38": "06",
    "l10n_co_tax_39": "06",
    "l10n_co_tax_40": "06",
    "l10n_co_tax_41": "06",
    "l10n_co_tax_42": "06",
    "l10n_co_tax_43": "07",
    "l10n_co_tax_44": "07",
    "l10n_co_tax_45": "07",
    "l10n_co_tax_46": "07",
    "l10n_co_tax_47": "07",
    "l10n_co_tax_48": "07",
    "l10n_co_tax_49": "01",
    "l10n_co_tax_50": "01",
    "l10n_co_tax_51": "01",
    "l10n_co_tax_52": "01",
    "l10n_co_tax_53": "06",
    "l10n_co_tax_54": "06",
    "l10n_co_tax_55": "05",
    "l10n_co_tax_56": "05",
    "l10n_co_tax_57": "07",
    "l10n_co_tax_58": "07",
    "l10n_co_tax_59": "04",
    "l10n_co_tax_60": "04",
    "l10n_co_tax_61": "04",
    "l10n_co_tax_62": "04",
    "l10n_co_tax_63": "04",
    "l10n_co_tax_64": "04",
    "l10n_co_tax_covered_goods": "01",
}


def post_init_hook(env):
    for base_xml_id, tax_type in TAX_TYPE_MAP.items():
        records = env["account.tax"].search([
            ("connector_dian_tax_type", "!=", tax_type),
        ])
        records_to_update = env["account.tax"]
        cr = env.cr
        cr.execute(
            """SELECT DISTINCT res_id FROM ir_model_data
               WHERE model = 'account.tax'
                 AND name LIKE %s""",
            (f"%{base_xml_id}",),
        )
        for (res_id,) in cr.fetchall():
            records_to_update |= env["account.tax"].browse(res_id)
        if records_to_update:
            records_to_update.write({"connector_dian_tax_type": tax_type})

    if hasattr(env["res.city"], "l10n_co_edi_code"):
        env.cr.execute(
            """UPDATE res_city
               SET connector_dane_code = l10n_co_edi_code::varchar
               WHERE l10n_co_edi_code IS NOT NULL
                 AND (connector_dane_code IS NULL OR connector_dane_code = '')"""
        )

    env.cr.execute(
        """UPDATE res_country
           SET enforce_cities = TRUE
           WHERE code = 'CO'"""
    )

    env.cr.execute(
        """UPDATE res_country_state
           SET connector_dane_code = CASE code
               WHEN 'AMA' THEN '91' WHEN 'ANT' THEN '05' WHEN 'ARA' THEN '81'
               WHEN 'ATL' THEN '08' WHEN 'BOL' THEN '13' WHEN 'BOY' THEN '15'
               WHEN 'CAL' THEN '17' WHEN 'CAQ' THEN '18' WHEN 'CAS' THEN '85'
               WHEN 'CAU' THEN '19' WHEN 'CES' THEN '20' WHEN 'CHO' THEN '27'
               WHEN 'COR' THEN '23' WHEN 'CUN' THEN '25' WHEN 'DC'  THEN '11'
               WHEN 'GUA' THEN '94' WHEN 'GUV' THEN '95' WHEN 'HUI' THEN '41'
               WHEN 'LAG' THEN '44' WHEN 'MAG' THEN '47' WHEN 'MET' THEN '50'
               WHEN 'NAR' THEN '52' WHEN 'NSA' THEN '54' WHEN 'PUT' THEN '86'
               WHEN 'QUI' THEN '63' WHEN 'RIS' THEN '66' WHEN 'SAN' THEN '68'
               WHEN 'SAP' THEN '88' WHEN 'SUC' THEN '70' WHEN 'TOL' THEN '73'
               WHEN 'VAC' THEN '76' WHEN 'VAU' THEN '97' WHEN 'VID' THEN '99'
               ELSE connector_dane_code
           END
           WHERE country_id = (SELECT id FROM res_country WHERE code = 'CO')
             AND (connector_dane_code IS NULL OR connector_dane_code = '')"""
    )

    env["account.tax"]._connector_assign_dian_tax_groups()
