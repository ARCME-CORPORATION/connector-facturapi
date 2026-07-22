import base64
import json
import logging

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _to_str(value):
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="replace")
        if decoded.startswith("-----"):
            return decoded
        try:
            return base64.b64decode(decoded).decode("utf-8")
        except Exception:
            return decoded
    return value


class FacturAPIClient:

    def __init__(self, base_url, api_key, company_id=None):
        self.base_url = base_url.rstrip("/")
        if company_id:
            token = f"{company_id}:{api_key}"
        else:
            token = api_key
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def upload_certificate(self, certificate, company_id):
        certificate.ensure_one()
        if not certificate.is_valid:
            raise UserError(_("Certificate is not valid."))
        if not certificate.private_key_id:
            raise UserError(_("Certificate has no private key."))

        cert_pem = _to_str(certificate.pem_certificate)
        key_pem = _to_str(certificate.private_key_id.pem_key)

        payload = {
            "certificate_pem": cert_pem,
            "private_key_pem": key_pem,
            "name": certificate.name or "Certificado DIAN",
        }

        url = f"{self.base_url}/api/v1/companies/{company_id}/certificate"
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            raise UserError(_("Cannot connect to FacturAPI server at %s") % self.base_url)
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text[:500]
            raise UserError(_("Certificate upload failed: %s") % detail)
        except requests.exceptions.RequestException as e:
            raise UserError(_("Request failed: %s") % e)

    def get_numbering_range(self, nit, software_code, environment="produccion"):
        payload = {
            "nit": nit,
            "software_code": software_code,
            "environment": environment,
        }

        url = f"{self.base_url}/api/v1/companies/numbering-range"
        try:
            response = requests.post(url, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.ConnectionError:
            raise UserError(_("Cannot connect to FacturAPI server at %s") % self.base_url)
        except requests.exceptions.HTTPError as e:
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text[:500]
            raise UserError(_("DIAN error: %s") % detail)
        except requests.exceptions.RequestException as e:
            raise UserError(_("Request failed: %s") % e)
