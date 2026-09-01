# Copyright 2026 Juan Arcos
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl).

import base64
import json
import logging
import time
from datetime import datetime, timezone, timedelta

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _fmt(val, default="0.00"):
    """Format a monetary value as XX.XX for the nómina XML."""
    if val in (None, ""):
        return default
    try:
        return f"{float(val):.2f}"
    except (ValueError, TypeError):
        return default


def _ident_type_code(partner_or_employee):
    """DIAN tipo documento (11 CI, 12 TI, 13 RC, 22 CE, 31 NIT, 41 PA...)."""
    id_type = getattr(partner_or_employee, "l10n_latam_identification_type_id", None)
    if not id_type:
        return "11"
    code_map = {
        "13": "13",  # Registro civil
        "11": "11",  # Cédula de ciudadanía
        "12": "12",  # Tarjeta de identidad
        "22": "22",  # Cédula de extranjería
        "31": "31",  # NIT
        "41": "41",  # Pasaporte
        "50": "50",  # PEP
        "48": "48",  # PPT
    }
    return code_map.get(
        getattr(id_type, "l10n_co_document_code", "")
        or getattr(id_type, "code", ""),
        "11",
    )


def _clean_prefix(prefix):
    import re

    cleaned = re.sub(r"%\([^)]*\)s", "", prefix).strip("/- ")
    return cleaned[:10]


class FacturapiNominaNe(models.Model):
    _name = "facturapi.nomina.ne"
    _description = "FacturAPI DIAN Nomina Electronica Document"
    _rec_name = "name"
    _order = "create_date desc"

    name = fields.Char(string="Document Reference", readonly=True)
    payslip_id = fields.Many2one(
        "hr.payslip", string="Payslip", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one("res.company", string="Company", required=True)

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
    connector_dian_accepted_datetime = fields.Datetime(
        string="DIAN Accepted At", readonly=True, copy=False
    )

    task_id = fields.Char(string="FacturAPI Task ID", index=True, copy=False)
    sequence_prefix = fields.Char(string="Prefijo", copy=False)
    sequence_number = fields.Integer(string="Consecutivo", copy=False)

    cune = fields.Char(string="CUNE", copy=False)
    qr_code = fields.Text(string="QR Code (Base64)", copy=False)
    xml_signed = fields.Text(string="Signed XML", copy=False)
    pdf_file = fields.Text(string="PDF (Base64)", copy=False)
    application_response = fields.Text(string="Application Response", copy=False)

    dian_status = fields.Char(string="DIAN Status Code", copy=False)
    dian_message = fields.Text(string="DIAN Status Message", copy=False)
    error_message = fields.Text(string="Error Message", copy=False)
    dian_error_details = fields.Text(string="DIAN Error Details", copy=False)

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------

    def _get_api_url(self):
        url = self.company_id.facturapi_api_url
        if not url:
            raise UserError(
                _("FacturAPI URL not configured for company %s")
                % self.company_id.name
            )
        return url.rstrip("/") + "/api/v1"

    def _get_headers(self):
        company = self.company_id
        token = f"{company.facturapi_company_id}:{company.facturapi_api_key}"
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Payload builder (from hr.payslip)
    # ------------------------------------------------------------------

    def _build_employer(self, slip):
        company = slip.company_id
        partner = company.partner_id
        vat = (partner.vat or "").strip()
        if "-" in vat:
            vat = vat.rsplit("-", 1)[0]
        dv = getattr(partner, "l10n_co_verification_digit", "") or ""
        return {
            "name": partner.commercial_company_name or partner.name or "",
            "identification_number": vat,
            "dv": dv,
            "country": "CO",
            "department_state": (
                getattr(partner.state_id, "connector_dane_code", "")
                or (partner.state_id.code if partner.state_id else "")
                or ""
            ),
            "city": (
                getattr(partner.city_id, "connector_dane_code", "")
                if partner.city_id
                else ""
            ),
            "address": partner.street or "",
        }

    def _build_worker(self, slip):
        emp = slip.employee_id
        contract = slip.contract_id or getattr(emp, "contract_id", False)
        # Salario: contrato o rule basica
        wage = float(getattr(contract, "wage", 0) or 0) if contract else 0.0
        id_number = (
            getattr(emp, "l10n_latam_identification_number", "")
            or getattr(emp, "identification_id", "")
            or ""
        )
        ident_type = _ident_type_code(emp)
        # Para personas naturales DIAN usa 11 (CC) por defecto
        if ident_type == "31":
            ident_type = "11"

        tipo_contrato = "1"
        if contract and getattr(contract, "contract_type", False):
            tipo_contrato = {
                "c": "1",  # Fijo
                "i": "2",  # Indefinido
                "t": "3",  # Temporal / obra
                "o": "4",  # Otro
            }.get(contract.contract_type or "", "1")

        name = emp.name or ""
        parts = name.split()
        first_name = getattr(emp, "first_name", "") or (parts[0] if parts else "")
        first_last = getattr(emp, "last_name", "") or (
            " ".join(parts[1:]) if len(parts) > 1 else ""
        )

        return {
            "tipo_trabajador": "1",  # Dependiente
            "subtipo_trabajador": str(
                getattr(contract, "l10n_co_worker_type", None) or "01"
            ),
            "alto_riesgo_pension": str(
                bool(getattr(contract, "l10n_co_high_risk_pension", False))
            ).lower(),
            "identification_type": ident_type,
            "identification_number": id_number,
            "first_last_name": first_last or name,
            "second_last_name": getattr(emp, "name2", "") or "",
            "first_name": first_name,
            "middle_name": "",
            "salary": _fmt(wage),
            "code": emp.id,
            "tipo_contrato": tipo_contrato,
            "salario_integral": str(
                bool(getattr(contract, "l10n_co_integral_salary", False))
            ).lower(),
        }

    def _build_period(self, slip):
        return {
            "ingreso": fields.Date.to_string(slip.date_from) if slip.date_from else "",
            "liq_inicio": (
                fields.Date.to_string(slip.date_from) if slip.date_from else ""
            ),
            "liq_fin": fields.Date.to_string(slip.date_to) if slip.date_to else "",
            "dias_trabajados": int(getattr(slip, "l10n_co_worked_days", 0) or 0),
        }

    def _build_earnings(self, slip):
        """Map devengados from the payslip lines into DIAN nómina categories."""
        earnings = {}
        basic = 0.0
        salarial = 0.0
        no_salarial = 0.0
        aux_transport = 0.0

        for line in slip.line_ids:
            total = float(line.total or 0.0)
            code = (line.code or "").upper()
            cat = line.category_id.code or ""
            if code == "BASIC":
                basic += total
            elif code == "AUX_TRANSPORT":
                aux_transport += total
                no_salarial += total
            elif code in ("EXTRAS", "COMMISSIONS", "OTHER_SALARY"):
                salarial += total
            elif cat in ("SALARIAL",):
                salarial += total
            elif cat in ("NO_SALARIAL",):
                no_salarial += total
            elif cat in ("BASIC",):
                basic += total

        if basic:
            earnings["basico"] = {"dias": slip.date_to.day or 30, "sueldo": basic}
        if aux_transport:
            earnings["transporte"] = {"aux": aux_transport}
        if salarial:
            earnings["otros_salariales"] = {
                "descripcion": "Otros devengados salariales",
                "s": salarial,
            }
        return earnings

    def _build_deductions(self, slip):
        """Map deducciones from the payslip lines into DIAN nómina categories."""
        deductions = {}
        salud = 0.0
        pension = 0.0
        otros = 0.0
        retencion = 0.0

        for line in slip.line_ids:
            total = float(line.total or 0.0)
            code = (line.code or "").upper()
            if code == "HEALTH_EMP_DEDUCTION":
                salud += abs(total)
            elif code == "PENSION_EMP_DEDUCTION":
                pension += abs(total)
            elif code in ("OTHER_DEDUCTIONS", "DEDUCTION"):
                otros += abs(total)
            elif "RETENCION" in code or "RETE" in code:
                retencion += abs(total)

        if salud:
            deductions["salud"] = {"porcentaje": 4.0, "deduccion": salud}
        if pension:
            deductions["pension"] = {"porcentaje": 4.0, "deduccion": pension}
        if otros:
            deductions["otros"] = otros
        if retencion:
            deductions["retencion_fuente"] = retencion
        return deductions

    def _build_payment(self, slip):
        contract = slip.contract_id
        bank = ""
        account_type = ""
        account_number = ""
        if contract:
            bank = contract.bank_id.name if contract.bank_id else ""
            account_type = "1"  # Ahorros
            account_number = (
                contract.bank_account_id
                and contract.bank_account_id.acc_number
                or ""
            )
        pay_date = slip.date_to
        if slip.payslip_run_id:
            pay_date = slip.payslip_run_id.date_end or pay_date
        return {
            "forma": "1",  # Efectivo
            "metodo": "1",  # Efectivo
            "banco": bank,
            "tipo_cuenta": account_type,
            "numero_cuenta": account_number,
            "date": fields.Date.to_string(pay_date) if pay_date else "", 
        }

    def _next_sequence_number(self, company):
        """Return (prefix, next_number) for the per-company nómina sequence."""
        prefix = _clean_prefix(getattr(company, "connector_ne_prefix", "") or "NP")
        code = "%s.nomina.electronica" % company.id
        seq = self.env["ir.sequence"].search([("code", "=", code)], limit=1)
        if not seq:
            seq = self.env["ir.sequence"].create({
                "name": f"Nómina Electrónica {company.name}",
                "code": code,
                "prefix": prefix,
                "padding": 8,
                "number_increment": 1,
                "company_id": company.id,
            })
        try:
            number = int(seq.next_by_id())
        except (ValueError, TypeError):
            number = 0
        return prefix, number

    def _payslip_total(self, slip, earnings_categories=False,
                       deductions_only=False, net_only=False):
        """Sum payslip line totals by category, independent of the localization
        module so connector_facturapi_ne does not need to depend on it."""
        devengo = {"BASIC", "SALARIAL", "NO_SALARIAL"}
        deduccion = {"DEDUCTION"}
        net = {"NET"}
        total = 0.0
        for line in slip.line_ids:
            cat = line.category_id.code or ""
            if net_only:
                if cat in net:
                    total += float(line.total or 0.0)
            elif deductions_only:
                if cat in deduccion:
                    total += float(line.total or 0.0)
            elif earnings_categories:
                if cat in devengo or cat in net:
                    total += float(line.total or 0.0)
        return total

    def _build_facturapi_payload(self, slip):
        company = slip.company_id
        if not company.facturapi_company_id or not company.facturapi_api_key:
            raise UserError(
                _("FacturAPI not configured for company %s") % company.name
            )

        # Número de secuencia nómina: por compañía
        prefix, seq_number = self._next_sequence_number(company)
        self.sequence_prefix = prefix
        self.sequence_number = seq_number

        total_earnings = _fmt(self._payslip_total(slip, earnings_categories=True))
        total_deductions = _fmt(
            abs(self._payslip_total(slip, deductions_only=True))
        )
        total_paid = _fmt(self._payslip_total(slip, net_only=True))

        environment = (
            company.connector_dian_environment or "habilitacion"
        )
        # DIAN: 1 = producción, 2 = habilitación (pruebas)
        ambiente_dian = "1" if environment == "produccion" else "2"

        co_tz = timezone(timedelta(hours=-5))
        issue_time_str = datetime.now(co_tz).strftime("%H:%M:%S-05:00")

        payload = {
            "company_id": company.facturapi_company_id or str(company.id),
            "document_type": "payroll",
            "document_type_code": "04",
            "environment": environment,
            "software_id": company.connector_software_id or "",
            "software_pin": company.connector_software_pin or "",
            "software_nit": (company.partner_id.vat or "").rsplit("-", 1)[0],
            "software_nit_dv": getattr(
                company.partner_id, "l10n_co_verification_digit", ""
            )
            or "",
            "test_set_id": (company.connector_test_set_id or "").replace(" ", ""),
            "prefix": self.sequence_prefix,
            "number": str(self.sequence_number),
            "issue_date": fields.Date.today().isoformat(),
            "issue_time": issue_time_str,
            "currency": "COP",
            "ambiente_dian": ambiente_dian,
            "employer": self._build_employer(slip),
            "worker": self._build_worker(slip),
            "period": self._build_period(slip),
            "earnings": self._build_earnings(slip),
            "deductions": self._build_deductions(slip),
            "payment": self._build_payment(slip),
            "total_earnings": total_earnings,
            "total_deductions": total_deductions,
            "total_paid": total_paid,
            "notes": "",
        }
        return payload

    # ------------------------------------------------------------------
    # Web service
    # ------------------------------------------------------------------

    def _post_to_web_service(self):
        self.ensure_one()
        slip = self.payslip_id
        payload = self._build_facturapi_payload(slip)

        base_url = self._get_api_url()
        url = f"{base_url}/documents/submit"
        response = requests.post(
            url, json=payload, headers=self._get_headers(), timeout=120
        )

        if response.status_code == 401:
            raise UserError(_(
                "FacturAPI rechazó el acceso (401 Unauthorized). Verifique que el "
                "Company ID y la API Key de la empresa '%s' sean correctos.",
                self.company_id.name,
            ))
        if response.status_code >= 400:
            self.write({
                "state": "rejected",
                "error_message": _("Error de FacturAPI (%s): %s") % (
                    response.status_code, response.text[:500],
                ),
            })
            raise UserError(
                _("El backend FacturAPI respondió con error (%s).")
                % response.status_code
            )

        response.raise_for_status()
        result = response.json()
        self.write({
            "task_id": result.get("task_id"),
            "state": "processing",
        })
        _logger.info(
            "FacturAPI nomina task created: %s for payslip %s",
            result.get("task_id"), slip.name,
        )

    def _check_task_status(self):
        self.ensure_one()
        if not self.task_id:
            return
        base_url = self._get_api_url()
        url = f"{base_url}/documents/{self.task_id}/status"
        response = requests.get(url, headers=self._get_headers(), timeout=120)
        if response.status_code == 401:
            raise UserError(_(
                "FacturAPI rechazó el acceso (401 Unauthorized). Verifique que el "
                "Company ID y la API Key de la empresa '%s' sean correctos.",
                self.company_id.name,
            ))
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

    def _fetch_and_process_result(self):
        self.ensure_one()
        base_url = self._get_api_url()
        url = f"{base_url}/documents/{self.task_id}/result"
        response = requests.get(url, headers=self._get_headers(), timeout=120)
        if response.status_code == 409:
            _logger.info("Result not ready yet for %s (409)", self.name)
            return False
        if response.status_code == 401:
            raise UserError(_(
                "FacturAPI rechazó el acceso (401 Unauthorized). Verifique que el "
                "Company ID y la API Key de la empresa '%s' sean correctos.",
                self.company_id.name,
            ))
        response.raise_for_status()
        data = response.json()

        dian_status = data.get("dian_status", "")
        is_accepted = dian_status in ("00", "100")
        is_pending = dian_status == "67"

        write_vals = {
            "cune": data.get("cufe_cude", ""),
            "qr_code": data.get("qr_code", ""),
            "xml_signed": data.get("xml_signed", ""),
            "pdf_file": data.get("pdf_file", ""),
            "application_response": data.get("application_response", ""),
            "dian_status": dian_status,
            "dian_error_details": data.get("dian_error_details", ""),
        }
        if is_accepted:
            write_vals["state"] = "accepted"
            write_vals["error_message"] = False
            write_vals["connector_dian_accepted_datetime"] = fields.Datetime.now()
        elif is_pending:
            write_vals["state"] = "processing"
            write_vals["error_message"] = "DIAN status 67: No events associated yet"
        else:
            write_vals["state"] = "rejected"
            write_vals["error_message"] = self._parse_dian_rejection(
                data.get("application_response", ""),
                data.get("dian_error_details", ""),
                dian_status,
            )
        self.write(write_vals)
        _logger.info(
            "DIAN nomina: payslip=%s task=%s status=%s",
            self.payslip_id.name or self.payslip_id.id,
            self.task_id, dian_status,
        )
        return True

    def _parse_dian_rejection(self, application_response, dian_error_details, dian_status):
        messages = []
        if dian_error_details:
            try:
                details = (
                    json.loads(dian_error_details)
                    if isinstance(dian_error_details, str)
                    else dian_error_details
                )
                for item in details:
                    code = item.get("code", "")
                    desc = item.get("description", "")
                    if code and desc:
                        messages.append(f"{code}: {desc}")
                    elif desc:
                        messages.append(desc)
            except (ValueError, TypeError):
                pass
        if not messages and application_response:
            try:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(application_response)
                for elem in root.iter():
                    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                    if tag == "StatusDescription" and elem.text:
                        messages.append(f"{dian_status}: {elem.text}")
                    elif tag == "ErrorMessage" and elem.text:
                        messages.append(elem.text)
            except Exception:
                pass
        if not messages:
            messages.append(f"DIAN status: {dian_status}")
        return "\n".join(messages)

    @api.model
    def _cron_check_dian_status(self):
        processing = self.search([("state", "=", "processing")])
        for doc in processing:
            try:
                doc._check_task_status()
            except Exception as e:
                _logger.error(
                    "Failed to check DIAN status for %s: %s", doc.name, e
                )
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
